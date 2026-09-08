from app import app, db
from models import AcademicActivity, Assessment, Attendance, Subject, User


TEST_EMAILS = ("module6.owner@example.com", "module6.other@example.com")


def test_activity_tracking_and_ownership():
    app.config.update(TESTING=True)
    created_user_ids = []
    created_activity_ids = []

    with app.app_context():
        assert not User.query.filter(User.email.in_(TEST_EMAILS)).first(), (
            "A Module 6 test account already exists; refusing to delete it."
        )

    client = app.test_client()
    assert client.get("/activities").status_code == 302
    assert client.get("/activities/add").status_code == 302

    try:
        for email, student_id in zip(TEST_EMAILS, ("M6-OWNER", "M6-OTHER")):
            response = client.post(
                "/register",
                data={
                    "full_name": "Module 6 Test",
                    "student_id": student_id,
                    "email": email,
                    "password": "testpass123",
                },
            )
            assert response.status_code == 302
            with app.app_context():
                created_user_ids.append(User.query.filter_by(email=email).first().id)

        client.post("/login", data={"email": TEST_EMAILS[0], "password": "testpass123"})
        assert b"No activities found" in client.get("/activities").data
        assert client.post("/subjects/add", data={"name": "Networks", "code": "CS601"}).status_code == 302
        with app.app_context():
            subject = Subject.query.filter_by(user_id=created_user_ids[0]).first()
            subject_id = subject.id
            attendance_before = Attendance.query.filter_by(user_id=created_user_ids[0]).count()
            assessments_before = Assessment.query.filter_by(user_id=created_user_ids[0]).count()

        base_data = {
            "title": "Department Seminar",
            "description": "Presented a seminar for the department.",
            "activity_category": "Academic",
            "activity_type": "Seminar",
            "activity_date": "2026-09-01",
            "subject_id": subject_id,
            "organizer": "CSE Department",
            "location": "Seminar Hall",
        }
        response = client.post("/activities/add", data=base_data)
        assert response.status_code == 302
        with app.app_context():
            academic = AcademicActivity.query.filter_by(user_id=created_user_ids[0]).first()
            assert academic.activity_category == "Academic"
            assert academic.verification_status == "Pending"
            assert academic.subject_id == subject_id
            created_activity_ids.append(academic.id)

        extra_data = {
            **base_data,
            "title": "Coding Competition",
            "description": "Participated in the college coding competition.",
            "activity_category": "Extra-Curricular",
            "activity_type": "Competition",
            "activity_date": "2026-09-02",
            "subject_id": "",
        }
        assert client.post("/activities/add", data=extra_data).status_code == 302
        with app.app_context():
            extra = AcademicActivity.query.filter_by(title="Coding Competition").first()
            assert extra.activity_category == "Extra-Curricular"
            assert extra.subject_id is None
            assert extra.verification_status == "Pending"
            created_activity_ids.append(extra.id)
            assert Attendance.query.filter_by(user_id=created_user_ids[0]).count() == attendance_before
            assert Assessment.query.filter_by(user_id=created_user_ids[0]).count() == assessments_before

        invalid_category = client.post("/activities/add", data={**base_data, "activity_category": "Attendance"})
        invalid_status = client.post("/activities/add", data={**base_data, "verification_status": "Verified"})
        invalid_subject = client.post("/activities/add", data={**base_data, "subject_id": "999999"})
        assert invalid_category.status_code == 200 and b"valid activity category" in invalid_category.data
        assert invalid_status.status_code == 200 and b"future review workflow" in invalid_status.data
        assert invalid_subject.status_code == 200 and b"one of your subjects" in invalid_subject.data
        with app.app_context():
            assert AcademicActivity.query.filter_by(title="Department Seminar").count() == 1

        activities_response = client.get("/activities?category=Extra-Curricular&activity_type=Competition")
        assert activities_response.status_code == 200
        assert b"Coding Competition" in activities_response.data
        assert b"Department Seminar" not in activities_response.data
        assert client.get(f"/activities/{created_activity_ids[0]}").status_code == 200

        edit_response = client.post(
            f"/activities/{created_activity_ids[0]}/edit",
            data={**base_data, "title": "Edited Seminar"},
        )
        assert edit_response.status_code == 302
        with app.app_context():
            academic = db.session.get(AcademicActivity, created_activity_ids[0])
            assert academic.title == "Edited Seminar"
            assert academic.verification_status == "Pending"

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[1], "password": "testpass123"})
        assert client.get(f"/activities/{created_activity_ids[0]}").status_code == 404
        assert client.get(f"/activities/{created_activity_ids[0]}/edit").status_code == 404
        assert client.post(f"/activities/{created_activity_ids[0]}/delete").status_code == 404
        with app.app_context():
            assert db.session.get(AcademicActivity, created_activity_ids[0]) is not None

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[0], "password": "testpass123"})
        assert client.post(f"/activities/{created_activity_ids[0]}/delete").status_code == 302
        with app.app_context():
            assert db.session.get(AcademicActivity, created_activity_ids[0]) is None
    finally:
        with app.app_context():
            for activity_id in created_activity_ids:
                activity = db.session.get(AcademicActivity, activity_id)
                if activity is not None:
                    db.session.delete(activity)
            for user_id in created_user_ids:
                user = db.session.get(User, user_id)
                if user is not None:
                    db.session.delete(user)
            db.session.commit()
