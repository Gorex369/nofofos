from app import app, db
from models import Assessment, Attendance, Subject, User


TEST_EMAILS = ("module5.owner@example.com", "module5.other@example.com")


def test_dashboard_overview_and_ownership_isolation():
    app.config.update(TESTING=True)
    created_user_ids = []

    with app.app_context():
        assert not User.query.filter(User.email.in_(TEST_EMAILS)).first(), (
            "A Module 5 test account already exists; refusing to delete it."
        )

    client = app.test_client()
    assert client.get("/dashboard").status_code == 302

    try:
        for email, student_id in zip(TEST_EMAILS, ("M5-OWNER", "M5-OTHER")):
            response = client.post(
                "/register",
                data={
                    "full_name": "Module 5 Test",
                    "student_id": student_id,
                    "email": email,
                    "password": "testpass123",
                },
            )
            assert response.status_code == 302
            with app.app_context():
                created_user_ids.append(User.query.filter_by(email=email).first().id)

        client.post("/login", data={"email": TEST_EMAILS[0], "password": "testpass123"})
        assert b"No Data" in client.get("/dashboard").data
        assert b"No attendance data has been entered yet" not in client.get("/dashboard").data

        assert client.post("/subjects/add", data={"name": "Mathematics", "code": "MATH501"}).status_code == 302
        assert client.post("/subjects/add", data={"name": "Networks", "code": "CS502"}).status_code == 302
        with app.app_context():
            subjects = Subject.query.filter_by(user_id=created_user_ids[0]).order_by(Subject.id).all()
            first_subject_id, second_subject_id = subjects[0].id, subjects[1].id

        assert client.post(
            "/attendance/add",
            data={"subject_id": first_subject_id, "record_date": "2026-09-01", "status": "Present"},
        ).status_code == 302
        assert client.post(
            "/attendance/add",
            data={"subject_id": first_subject_id, "record_date": "2026-09-02", "status": "Absent"},
        ).status_code == 302
        for title, obtained, maximum in (("Unit Test", "10", "10"), ("Final Exam", "50", "100")):
            assert client.post(
                "/assessments/add",
                data={
                    "subject_id": first_subject_id,
                    "assessment_type": "Other",
                    "assessment_title": title,
                    "assessment_date": "2026-09-03",
                    "marks_obtained": obtained,
                    "maximum_marks": maximum,
                },
            ).status_code == 302

        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert b"50.00%" in dashboard.data
        assert b"54.55%" in dashboard.data
        assert b"Mathematics" in dashboard.data and b"Networks" in dashboard.data
        assert b"Needs Attention" in dashboard.data
        assert b"No Data" in dashboard.data

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[1], "password": "testpass123"})
        other_dashboard = client.get("/dashboard")
        assert other_dashboard.status_code == 200
        assert b"Mathematics" not in other_dashboard.data
        assert b"Networks" not in other_dashboard.data
        assert b"No Data" in other_dashboard.data

        with app.app_context():
            assert Attendance.query.filter_by(user_id=created_user_ids[0]).count() == 2
            assert Assessment.query.filter_by(user_id=created_user_ids[0]).count() == 2
    finally:
        with app.app_context():
            for user_id in created_user_ids:
                user = db.session.get(User, user_id)
                if user is not None:
                    db.session.delete(user)
            db.session.commit()
