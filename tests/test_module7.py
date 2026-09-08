from io import BytesIO
import os

from sqlalchemy.exc import IntegrityError

from app import app, db
from models import AcademicActivity, Assessment, Attendance, EvidenceAttachment, Subject, User


TEST_EMAILS = ("module7.owner@example.com", "module7.other@example.com")


def upload_data(filename="certificate.pdf", content=b"%PDF-1.7 evidence", content_type="application/pdf"):
    return {"evidence_file": (BytesIO(content), filename, content_type), "description": "Supporting evidence"}


def test_evidence_attachment_security_and_storage():
    app.config.update(TESTING=True)
    created_user_ids = []
    created_evidence_ids = []
    upload_dir = app.config["EVIDENCE_UPLOAD_DIR"]

    with app.app_context():
        assert not User.query.filter(User.email.in_(TEST_EMAILS)).first(), (
            "A Module 7 test account already exists; refusing to delete it."
        )

    client = app.test_client()
    assert client.get("/activities/1/evidence/add").status_code == 302
    assert client.get("/assessments/1/evidence/add").status_code == 302
    assert client.get("/attendance/1/evidence/add").status_code == 302

    try:
        for email, student_id in zip(TEST_EMAILS, ("M7-OWNER", "M7-OTHER")):
            response = client.post(
                "/register",
                data={
                    "full_name": "Module 7 Test",
                    "student_id": student_id,
                    "email": email,
                    "password": "testpass123",
                },
            )
            assert response.status_code == 302
            with app.app_context():
                created_user_ids.append(User.query.filter_by(email=email).first().id)

        client.post("/login", data={"email": TEST_EMAILS[0], "password": "testpass123"})
        assert client.get("/activities").status_code == 200
        assert client.post("/activities/add", data={
            "title": "Research Seminar",
            "description": "A temporary activity for evidence testing.",
            "activity_category": "Academic",
            "activity_type": "Seminar",
            "activity_date": "2026-09-01",
        }).status_code == 302
        assert client.post("/subjects/add", data={"name": "Evidence Subject", "code": "EV701"}).status_code == 302
        with app.app_context():
            user_id = created_user_ids[0]
            activity = AcademicActivity.query.filter_by(user_id=user_id).first()
            subject = Subject.query.filter_by(user_id=user_id).first()
            activity_id, subject_id = activity.id, subject.id

        assert client.post("/attendance/add", data={
            "subject_id": subject_id, "record_date": "2026-09-01", "status": "Present"
        }).status_code == 302
        assert client.post("/assessments/add", data={
            "subject_id": subject_id,
            "assessment_type": "Other",
            "assessment_title": "Evidence Assessment",
            "assessment_date": "2026-09-01",
            "marks_obtained": "8",
            "maximum_marks": "10",
        }).status_code == 302
        with app.app_context():
            attendance = Attendance.query.filter_by(user_id=user_id).first()
            assessment = Assessment.query.filter_by(user_id=user_id).first()
            attendance_id, assessment_id = attendance.id, assessment.id
            attendance_total = Attendance.query.filter_by(user_id=user_id).count()
            assessment_total = Assessment.query.filter_by(user_id=user_id).count()
            activity_total = AcademicActivity.query.filter_by(user_id=user_id).count()

        parent_routes = (
            (f"/activities/{activity_id}/evidence/add", "activity_id", activity_id),
            (f"/assessments/{assessment_id}/evidence/add", "assessment_id", assessment_id),
            (f"/attendance/{attendance_id}/evidence/add", "attendance_id", attendance_id),
        )
        for route, parent_field, parent_id in parent_routes:
            response = client.post(route, data=upload_data(), content_type="multipart/form-data")
            assert response.status_code == 302
            with app.app_context():
                evidence = EvidenceAttachment.query.filter_by(
                    user_id=user_id, **{parent_field: parent_id}
                ).first()
                assert evidence is not None
                assert evidence.verification_status == "Pending"
                assert evidence.original_filename == "certificate.pdf"
                assert evidence.stored_filename != evidence.original_filename
                assert evidence.stored_filename.endswith(".pdf")
                assert os.path.basename(evidence.storage_path) == evidence.stored_filename
                assert os.path.isfile(evidence.storage_path)
                created_evidence_ids.append(evidence.id)

        with app.app_context():
            evidence = db.session.get(EvidenceAttachment, created_evidence_ids[0])
            assert sum(value is not None for value in (evidence.activity_id, evidence.assessment_id, evidence.attendance_id)) == 1
            before_files = set(os.listdir(upload_dir))
            try:
                invalid = EvidenceAttachment(
                    user_id=user_id,
                    original_filename="invalid.pdf",
                    stored_filename="invalid.pdf",
                    storage_path=os.path.join(upload_dir, "invalid.pdf"),
                    mime_type="application/pdf",
                    file_size=4,
                )
                db.session.add(invalid)
                db.session.commit()
                raise AssertionError("Evidence with zero parents was accepted")
            except IntegrityError:
                pass
            db.session.rollback()
            assert set(os.listdir(upload_dir)) == before_files

        invalid_extension = client.post(
            f"/activities/{activity_id}/evidence/add",
            data=upload_data("malware.exe", b"MZ executable", "application/octet-stream"),
            content_type="multipart/form-data",
        )
        assert invalid_extension.status_code == 200
        too_large = client.post(
            f"/activities/{activity_id}/evidence/add",
            data=upload_data("large.pdf", b"%PDF" + b"x" * (5 * 1024 * 1024)),
            content_type="multipart/form-data",
        )
        assert too_large.status_code == 413
        with app.app_context():
            assert EvidenceAttachment.query.filter_by(user_id=user_id).count() == 3
        assert set(os.listdir(upload_dir)) == before_files

        evidence_id = created_evidence_ids[0]
        response = client.get(f"/activities/{activity_id}/evidence/{evidence_id}")
        assert response.status_code == 200
        download = client.get(f"/activities/{activity_id}/evidence/{evidence_id}/download")
        assert download.status_code == 200
        assert download.data.startswith(b"%PDF")
        download.close()

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[1], "password": "testpass123"})
        assert client.get(f"/activities/{activity_id}/evidence/{evidence_id}").status_code == 404
        assert client.get(f"/activities/{activity_id}/evidence/{evidence_id}/download").status_code == 404
        assert client.post(f"/activities/{activity_id}/evidence/{evidence_id}/delete").status_code == 404
        assert client.post(
            f"/activities/{activity_id}/evidence/add",
            data=upload_data(),
            content_type="multipart/form-data",
        ).status_code == 404

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[0], "password": "testpass123"})
        stored_path = None
        with app.app_context():
            stored_path = db.session.get(EvidenceAttachment, evidence_id).storage_path
        assert client.post(f"/activities/{activity_id}/evidence/{evidence_id}/delete").status_code == 302
        assert not os.path.exists(stored_path)
        with app.app_context():
            assert db.session.get(EvidenceAttachment, evidence_id) is None
            assert Attendance.query.filter_by(user_id=user_id).count() == attendance_total
            assert Assessment.query.filter_by(user_id=user_id).count() == assessment_total
            assert AcademicActivity.query.filter_by(user_id=user_id).count() == activity_total
    finally:
        with app.app_context():
            db.session.rollback()
            for evidence_id in created_evidence_ids:
                evidence = db.session.get(EvidenceAttachment, evidence_id)
                if evidence is not None:
                    path = evidence.storage_path
                    db.session.delete(evidence)
                    db.session.commit()
                    if os.path.isfile(path) and os.path.commonpath([os.path.abspath(upload_dir), os.path.abspath(path)]) == os.path.abspath(upload_dir):
                        os.remove(path)
            for activity in AcademicActivity.query.filter(AcademicActivity.user_id.in_(created_user_ids)).all():
                db.session.delete(activity)
            for assessment in Assessment.query.filter(Assessment.user_id.in_(created_user_ids)).all():
                db.session.delete(assessment)
            for attendance in Attendance.query.filter(Attendance.user_id.in_(created_user_ids)).all():
                db.session.delete(attendance)
            for subject in Subject.query.filter(Subject.user_id.in_(created_user_ids)).all():
                db.session.delete(subject)
            for user_id in created_user_ids:
                user = db.session.get(User, user_id)
                if user is not None:
                    db.session.delete(user)
            db.session.commit()
