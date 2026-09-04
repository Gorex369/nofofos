from app import app, db
from models import Assessment, Subject, User


TEST_EMAILS = ("module4.owner@example.com", "module4.other@example.com")


def test_assessment_tracking_and_weighted_summary():
    app.config.update(TESTING=True)
    created_user_ids = []

    with app.app_context():
        assert not User.query.filter(User.email.in_(TEST_EMAILS)).first(), (
            "A Module 4 test account already exists; refusing to delete it."
        )

    client = app.test_client()
    assert client.get("/assessments").status_code == 302

    try:
        for email, student_id in zip(TEST_EMAILS, ("M4-OWNER", "M4-OTHER")):
            response = client.post(
                "/register",
                data={
                    "full_name": "Module 4 Test",
                    "student_id": student_id,
                    "email": email,
                    "password": "testpass123",
                },
            )
            assert response.status_code == 302
            with app.app_context():
                created_user_ids.append(User.query.filter_by(email=email).first().id)

        client.post("/login", data={"email": TEST_EMAILS[0], "password": "testpass123"})
        for name, code in (("Mathematics", "MATH401"), ("Networks", "CS402")):
            assert client.post("/subjects/add", data={"name": name, "code": code}).status_code == 302
        with app.app_context():
            subjects = Subject.query.filter_by(user_id=created_user_ids[0]).order_by(Subject.id).all()
            subject_id, second_subject_id = subjects[0].id, subjects[1].id

        zero_response = client.get(f"/assessments?subject_id={second_subject_id}")
        assert zero_response.status_code == 200
        assert b"No assessment data has been entered yet" in zero_response.data

        base_data = {
            "subject_id": subject_id,
            "assessment_type": "Class Test",
            "assessment_title": "Unit Test",
            "assessment_date": "2026-09-01",
            "remarks": "Module 4 test",
        }
        invalid_high = client.post("/assessments/add", data={**base_data, "marks_obtained": "11", "maximum_marks": "10"})
        invalid_negative = client.post("/assessments/add", data={**base_data, "marks_obtained": "-1", "maximum_marks": "10"})
        assert invalid_high.status_code == 200 and b"valid assessment details" in invalid_high.data
        assert invalid_negative.status_code == 200 and b"valid assessment details" in invalid_negative.data

        assert client.post("/assessments/add", data={**base_data, "marks_obtained": "10", "maximum_marks": "10"}).status_code == 302
        second_data = {**base_data, "assessment_type": "Other", "assessment_title": "Final Review", "assessment_date": "2026-09-02", "marks_obtained": "50", "maximum_marks": "100"}
        assert client.post("/assessments/add", data=second_data).status_code == 302

        with app.app_context():
            records = Assessment.query.filter_by(user_id=created_user_ids[0], subject_id=subject_id).all()
            assert len(records) == 2
            assessment_id = records[0].id
            assert not hasattr(Assessment, "percentage")

        all_response = client.get("/assessments")
        assert b"54.55%" in all_response.data
        assert b"10.00 / 10.00" in all_response.data
        assert b"50.00 / 100.00" in all_response.data
        filtered_response = client.get(f"/assessments?subject_id={subject_id}")
        assert filtered_response.status_code == 200
        assert filtered_response.data.count(b"Module 4 test") == 2

        edit_response = client.post(
            f"/assessments/{assessment_id}/edit",
            data={**base_data, "assessment_title": "Edited Test", "marks_obtained": "5", "maximum_marks": "10"},
        )
        assert edit_response.status_code == 302
        assert b"50.00%" in client.get(f"/assessments?subject_id={subject_id}").data

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[1], "password": "testpass123"})
        assert client.get(f"/assessments/{assessment_id}/edit").status_code == 404
        assert client.post(f"/assessments/{assessment_id}/delete").status_code == 404
        with app.app_context():
            assert db.session.get(Assessment, assessment_id) is not None

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[0], "password": "testpass123"})
        assert client.post(f"/assessments/{assessment_id}/delete").status_code == 302
        with app.app_context():
            assert db.session.get(Assessment, assessment_id) is None
    finally:
        with app.app_context():
            for user_id in created_user_ids:
                user = db.session.get(User, user_id)
                if user is not None:
                    db.session.delete(user)
            db.session.commit()
