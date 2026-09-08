from io import BytesIO
import os

from app import app, db
from models import AcademicReview, Assessment, EvidenceAttachment, Subject, User


TEST_EMAILS = ("module8a.owner@example.com", "module8a.other@example.com")


def evidence_upload():
    return {"evidence_file": (BytesIO(b"%PDF-1.7 review evidence"), "review.pdf", "application/pdf")}


def test_assessment_review_snapshot_security_and_evidence():
    app.config.update(TESTING=True)
    created_user_ids = []
    created_review_ids = []
    created_evidence_ids = []
    upload_dir = app.config["EVIDENCE_UPLOAD_DIR"]

    with app.app_context():
        assert not User.query.filter(User.email.in_(TEST_EMAILS)).first(), (
            "A Module 8A test account already exists; refusing to delete it."
        )

    client = app.test_client()
    assert client.get("/reviews").status_code == 302
    assert client.get("/assessments/1/review").status_code == 302

    try:
        for email, student_id in zip(TEST_EMAILS, ("M8A-OWNER", "M8A-OTHER")):
            response = client.post(
                "/register",
                data={
                    "full_name": "Module 8A Test",
                    "student_id": student_id,
                    "email": email,
                    "password": "testpass123",
                },
            )
            assert response.status_code == 302
            with app.app_context():
                created_user_ids.append(User.query.filter_by(email=email).first().id)

        client.post("/login", data={"email": TEST_EMAILS[0], "password": "testpass123"})
        assert client.post("/subjects/add", data={"name": "DBMS", "code": "CS801"}).status_code == 302
        with app.app_context():
            user_id = created_user_ids[0]
            subject = Subject.query.filter_by(user_id=user_id).first()
            subject_id = subject.id

        assert client.post("/assessments/add", data={
            "subject_id": subject_id,
            "assessment_type": "Mid-Term",
            "assessment_title": "DBMS Mid-Term",
            "assessment_date": "2026-09-01",
            "marks_obtained": "31",
            "maximum_marks": "50",
        }).status_code == 302
        with app.app_context():
            assessment = Assessment.query.filter_by(user_id=user_id).first()
            assessment_id = assessment.id
            attendance_total_before = 0
            assessment_total_before = Assessment.query.filter_by(user_id=user_id).count()

        no_difference = client.post(
            f"/assessments/{assessment_id}/review",
            data={"reviewed_marks_obtained": "31", "review_note": "Compared with the recorded value."},
        )
        assert no_difference.status_code == 302
        with app.app_context():
            review = AcademicReview.query.filter_by(user_id=user_id).first()
            assert review.recorded_marks_obtained == 31
            assert review.reviewed_marks_obtained == 31
            assert review.difference == 0
            assert review.review_status == "No Difference"
            created_review_ids.append(review.id)

        difference_no_note = client.post(
            f"/assessments/{assessment_id}/review",
            data={"reviewed_marks_obtained": "35", "review_note": ""},
        )
        assert difference_no_note.status_code == 200
        assert b"review note is required" in difference_no_note.data
        with app.app_context():
            assert AcademicReview.query.filter_by(user_id=user_id).count() == 1

        difference = client.post(
            f"/assessments/{assessment_id}/review",
            data={"reviewed_marks_obtained": "35", "review_note": "Compared against the submitted record."},
        )
        assert difference.status_code == 302
        with app.app_context():
            difference_review = AcademicReview.query.filter_by(user_id=user_id).order_by(AcademicReview.id.desc()).first()
            assert difference_review.recorded_marks_obtained == 31
            assert difference_review.difference == 4
            assert difference_review.review_status == "Difference Found"
            created_review_ids.append(difference_review.id)
            assert db.session.get(Assessment, assessment_id).marks_obtained == 31

        invalid_high = client.post(
            f"/assessments/{assessment_id}/review",
            data={"reviewed_marks_obtained": "51", "review_note": "Too high."},
        )
        invalid_negative = client.post(
            f"/assessments/{assessment_id}/review",
            data={"reviewed_marks_obtained": "-1", "review_note": "Negative."},
        )
        invalid_note = client.post(
            f"/assessments/{assessment_id}/review",
            data={"reviewed_marks_obtained": "31", "review_note": "x" * 1001},
        )
        assert invalid_high.status_code == 200
        assert invalid_negative.status_code == 200
        assert invalid_note.status_code == 200
        with app.app_context():
            assert AcademicReview.query.filter_by(user_id=user_id).count() == 2

        assert client.post(
            f"/assessments/{assessment_id}/evidence/add",
            data=evidence_upload(),
            content_type="multipart/form-data",
        ).status_code == 302
        with app.app_context():
            evidence = EvidenceAttachment.query.filter_by(assessment_id=assessment_id, user_id=user_id).first()
            assert evidence is not None
            created_evidence_ids.append(evidence.id)
            evidence_name = evidence.original_filename

        review_detail = client.get(f"/reviews/{created_review_ids[1]}")
        assert review_detail.status_code == 200
        assert evidence_name.encode() in review_detail.data
        assert b"Difference Found" in review_detail.data
        assert b"Recorded marks at review" in review_detail.data
        assert client.get("/reviews").status_code == 200

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[1], "password": "testpass123"})
        assert client.get(f"/assessments/{assessment_id}/review").status_code == 404
        assert client.get(f"/reviews/{created_review_ids[0]}").status_code == 404
        assert client.post(f"/reviews/{created_review_ids[0]}/delete").status_code == 404
        with app.app_context():
            assert AcademicReview.query.filter_by(id=created_review_ids[0]).first() is not None
            assert EvidenceAttachment.query.filter_by(id=created_evidence_ids[0]).first() is not None

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[0], "password": "testpass123"})
        assert client.post(f"/reviews/{created_review_ids[0]}/delete").status_code == 302
        with app.app_context():
            assert AcademicReview.query.filter_by(id=created_review_ids[0]).first() is None
            assert db.session.get(Assessment, assessment_id).marks_obtained == 31
            assert Assessment.query.filter_by(user_id=user_id).count() == assessment_total_before
            assert EvidenceAttachment.query.filter_by(id=created_evidence_ids[0]).first() is not None
    finally:
        with app.app_context():
            db.session.rollback()
            for review_id in created_review_ids:
                review = db.session.get(AcademicReview, review_id)
                if review is not None:
                    db.session.delete(review)
            for evidence_id in created_evidence_ids:
                evidence = db.session.get(EvidenceAttachment, evidence_id)
                if evidence is not None:
                    path = evidence.storage_path
                    db.session.delete(evidence)
                    db.session.commit()
                    if os.path.isfile(path) and os.path.commonpath([os.path.abspath(upload_dir), os.path.abspath(path)]) == os.path.abspath(upload_dir):
                        os.remove(path)
            for assessment in Assessment.query.filter(Assessment.user_id.in_(created_user_ids)).all():
                db.session.delete(assessment)
            for subject in Subject.query.filter(Subject.user_id.in_(created_user_ids)).all():
                db.session.delete(subject)
            for user_id in created_user_ids:
                user = db.session.get(User, user_id)
                if user is not None:
                    db.session.delete(user)
            db.session.commit()
