from app import app, db
from models import Subject, User


TEST_EMAILS = ("module2.owner@example.com", "module2.other@example.com")


def test_profile_and_subject_ownership():
    app.config.update(TESTING=True)
    created_user_ids = []

    with app.app_context():
        assert not User.query.filter(User.email.in_(TEST_EMAILS)).first(), (
            "A Module 2 test account already exists; refusing to delete it."
        )

    client = app.test_client()
    assert client.get("/profile").status_code == 302
    assert client.get("/subjects").status_code == 302

    try:
        for email, student_id in zip(TEST_EMAILS, ("M2-OWNER", "M2-OTHER")):
            response = client.post(
                "/register",
                data={
                    "full_name": "Module 2 Test",
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
            "/profile",
            data={
                "full_name": "Updated Module 2 Student",
                "student_id": "M2-OWNER-UPDATED",
                "branch": "CSE",
                "semester": "5",
                "section": "A",
            },
        )
        assert response.status_code == 302
        with app.app_context():
            owner = db.session.get(User, created_user_ids[0])
            assert owner.full_name == "Updated Module 2 Student"
            assert owner.email == TEST_EMAILS[0]
            assert (owner.branch, owner.semester, owner.section) == ("CSE", "5", "A")

        response = client.post(
            "/subjects/add",
            data={
                "name": "Data Structures",
                "code": "CS501",
                "faculty_name": "Dr. Test",
                "credits": "4",
            },
        )
        assert response.status_code == 302
        with app.app_context():
            subject = Subject.query.filter_by(user_id=created_user_ids[0]).first()
            assert subject is not None
            subject_id = subject.id

        response = client.post(
            f"/subjects/{subject_id}/edit",
            data={
                "name": "Advanced Data Structures",
                "code": "CS502",
                "faculty_name": "Prof. Test",
                "credits": "3",
            },
        )
        assert response.status_code == 302

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[1], "password": "testpass123"})
        assert client.get(f"/subjects/{subject_id}/edit").status_code == 404
        assert client.post(f"/subjects/{subject_id}/delete").status_code == 404
        with app.app_context():
            assert db.session.get(Subject, subject_id) is not None

        client.get("/logout")
        client.post("/login", data={"email": TEST_EMAILS[0], "password": "testpass123"})
        response = client.post(f"/subjects/{subject_id}/delete")
        assert response.status_code == 302
        with app.app_context():
            assert db.session.get(Subject, subject_id) is None
    finally:
        with app.app_context():
            for user_id in created_user_ids:
                user = db.session.get(User, user_id)
                if user is not None:
                    db.session.delete(user)
            db.session.commit()
