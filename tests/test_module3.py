from app import app, db
from models import Attendance, Subject, User


TEST_EMAILS = ("module3.owner@example.com", "module3.other@example.com")


def test_attendance_tracking_and_ownership():
    app.config.update(TESTING=True)
    created_user_ids = []

    with app.app_context():
        assert not User.query.filter(User.email.in_(TEST_EMAILS)).first(), (
            "A Module 3 test account already exists; refusing to delete it."
        )

    client = app.test_client()
    assert client.get("/attendance").status_code == 302

    try:
        for email, student_id in zip(TEST_EMAILS, ("M3-OWNER", "M3-OTHER")):
            response = client.post(
                "/register",
                data={
                    "full_name": "Module 3 Test",
                    "student_id": student_id,
                    "email": email,
                    "password": "testpass123",
                },
            )
            assert response.status_code == 302
            with app.app_context():
                created_user_ids.append(User.query.filter_by(email=email).first().id)

        client.post("/login", data={"email": TEST_EMAILS[0], "password": "testpass123"})
        response = client.post(
            "/subjects/add",
            data={"name": "Operating Systems", "code": "CS601", "credits": "4"},
        )
        assert response.status_code == 302
        with app.app_context():
            subject = Subject.query.filter_by(user_id=created_user_ids[0]).first()
            subject_id = subject.id

        zero_response = client.get(f"/attendance?subject_id={subject_id}")
        assert zero_response.status_code == 200
        assert b"No attendance records yet" in zero_response.data

        for record_date, status in (("2026-09-01", "Present"), ("2026-09-02", "Absent")):
            response = client.post(
                "/attendance/add",
                data={
                    "subject_id": subject_id,
                    "record_date": record_date,
                    "status": status,
                    "class_type": "Lecture",
                    "topic": "Module 3 test",
                },
            )
            assert response.status_code == 302

        with app.app_context():
            records = Attendance.query.filter_by(
                user_id=created_user_ids[0], subject_id=subject_id
            ).all()
            assert len(records) == 2
            attendance_id = records[0].id
            assert not hasattr(Attendance, "attendance_percentage")

        summary_response = client.get(f"/attendance?subject_id={subject_id}")
        assert b"50.00%" in summary_response.data
        assert b">2<" in summary_response.data

        response = client.post(
            f"/attendance/{attendance_id}/edit",
            data={
                "record_date": "2026-09-01",
                "status": "Absent",
                "class_type": "Lab",
                "topic": "Updated test topic",
            },
        )
        assert response.status_code == 302
        summary_response = client.get(f"/attendance?subject_id={subject_id}")
        assert b"0.00%" in summary_response.data

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[1], "password": "testpass123"})
        assert client.get(f"/attendance?subject_id={subject_id}").status_code == 200
        assert client.get(f"/attendance/{attendance_id}/edit").status_code == 404
        assert client.post(f"/attendance/{attendance_id}/delete").status_code == 404
        with app.app_context():
            assert db.session.get(Attendance, attendance_id) is not None

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[0], "password": "testpass123"})
        response = client.post(f"/attendance/{attendance_id}/delete")
        assert response.status_code == 302
        with app.app_context():
            assert db.session.get(Attendance, attendance_id) is None
    finally:
        with app.app_context():
            for user_id in created_user_ids:
                user = db.session.get(User, user_id)
                if user is not None:
                    db.session.delete(user)
            db.session.commit()
