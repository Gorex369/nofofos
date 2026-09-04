from app import app, db
from models import AcademicActivity, FacultyAssignment, Subject, User
from seed_demo_accounts import DEMO_ACCOUNTS, provision_demo_accounts


TEST_EMAILS = ("module8b.student@example.com", "module8b.faculty@example.com", "module8b.coordinator@example.com", "module8b.admin@example.com")


def register(client, email, student_id, extra=None):
    data = {
        "full_name": "Module 8B Test",
        "student_id": student_id,
        "email": email,
        "password": "testpass123",
    }
    if extra:
        data.update(extra)
    return client.post("/register", data=data)


def login(client, email):
    return client.post("/login", data={"email": email, "password": "testpass123"})


def test_role_authorization_assignments_and_safe_demo_provisioning():
    app.config.update(TESTING=True)
    created_user_ids = []
    created_activity_id = None
    assignment_id = None

    with app.app_context():
        assert not User.query.filter(User.email.in_(TEST_EMAILS)).first(), (
            "A Module 8B test account already exists; refusing to delete it."
        )
        created, skipped = provision_demo_accounts()
        assert not created
        assert {email for email, *_ in DEMO_ACCOUNTS} == set(skipped)
        for email, _, _, role in DEMO_ACCOUNTS:
            user = User.query.filter_by(email=email).first()
            assert user.role == role
            assert user.password_hash != "DemoOnly-2026!"

    client = app.test_client()
    assert client.get("/faculty/dashboard").status_code == 302
    assert client.get("/coordinator/dashboard").status_code == 302
    assert client.get("/admin/dashboard").status_code == 302

    try:
        for email, student_id in zip(TEST_EMAILS, ("M8B-STUDENT", "M8B-FACULTY", "M8B-COORD", "M8B-ADMIN")):
            assert register(client, email, student_id, {"role": "admin"}).status_code == 302
            with app.app_context():
                created_user_ids.append(User.query.filter_by(email=email).first().id)

        with app.app_context():
            student = db.session.get(User, created_user_ids[0])
            faculty = db.session.get(User, created_user_ids[1])
            coordinator = db.session.get(User, created_user_ids[2])
            admin = db.session.get(User, created_user_ids[3])
            faculty.role = "faculty"
            coordinator.role = "coordinator"
            admin.role = "admin"
            subject = Subject(name="Assigned Subject", code="M8B-101", user_id=student.id)
            db.session.add(subject)
            db.session.flush()
            assignment = FacultyAssignment(
                faculty_user_id=faculty.id,
                student_user_id=student.id,
                subject_id=subject.id,
                section="A",
            )
            db.session.add(assignment)
            db.session.commit()
            assignment_id = assignment.id
            subject_id = subject.id

        login(client, TEST_EMAILS[0])
        with client.session_transaction() as session_data:
            assert session_data["user_role"] == "student"
        assert client.get("/faculty/dashboard").status_code == 403
        assert client.get("/coordinator/dashboard").status_code == 403
        assert client.get("/admin/dashboard").status_code == 403
        assert client.post("/register", data={"role": "admin"}).status_code == 200
        client.get("/logout")

        login(client, TEST_EMAILS[1])
        assert client.get("/faculty/dashboard").status_code == 200
        assert client.get("/admin/dashboard").status_code == 403
        assert client.get("/coordinator/dashboard").status_code == 403
        with app.app_context():
            assignment = db.session.get(FacultyAssignment, assignment_id)
            assert assignment.student.email == TEST_EMAILS[0]
        client.get("/logout")

        login(client, TEST_EMAILS[0])
        assert client.post("/activities/add", data={
            "title": "Student Society Work",
            "description": "Temporary ECA submission.",
            "activity_category": "Extra-Curricular",
            "activity_type": "Society Work",
            "activity_date": "2026-09-04",
            "subject_id": subject_id,
        }).status_code == 302
        with app.app_context():
            activity = AcademicActivity.query.filter_by(user_id=created_user_ids[0]).first()
            created_activity_id = activity.id
        client.get("/logout")

        login(client, TEST_EMAILS[2])
        assert client.get("/coordinator/dashboard").status_code == 200
        assert client.get("/coordinator/activities").status_code == 200
        assert client.get(f"/coordinator/activities/{created_activity_id}").status_code == 200
        assert client.get(f"/activities/{created_activity_id}").status_code == 404
        assert client.get("/admin/dashboard").status_code == 403
        client.get("/logout")

        login(client, TEST_EMAILS[3])
        assert client.get("/admin/dashboard").status_code == 200
        assert client.get("/coordinator/dashboard").status_code == 200
        assert client.get("/coordinator/activities").status_code == 200
        client.get("/logout")
    finally:
        with app.app_context():
            if created_activity_id is not None:
                activity = db.session.get(AcademicActivity, created_activity_id)
                if activity is not None:
                    db.session.delete(activity)
            if assignment_id is not None:
                assignment = db.session.get(FacultyAssignment, assignment_id)
                if assignment is not None:
                    db.session.delete(assignment)
            for user_id in created_user_ids:
                user = db.session.get(User, user_id)
                if user is not None:
                    db.session.delete(user)
            db.session.commit()
