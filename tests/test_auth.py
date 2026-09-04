from app import app, db
from models import User


TEST_EMAIL = "foundation.check@example.com"
TEST_STUDENT_ID = "FOUND-001"


def test_authentication_flow_only_cleans_test_account():
    app.config.update(TESTING=True)

    with app.app_context():
        assert User.query.filter_by(email=TEST_EMAIL).first() is None, (
            "Refusing to delete an existing test account; clean it up manually "
            "before running this test."
        )

    client = app.test_client()
    assert client.get("/dashboard").status_code == 302
    assert client.get("/register").status_code == 200

    try:
        response = client.post(
            "/register",
            data={
                "full_name": "Foundation Check",
                "student_id": TEST_STUDENT_ID,
                "email": TEST_EMAIL,
                "password": "testpass123",
            },
        )
        assert response.status_code == 302

        with app.app_context():
            test_user = User.query.filter_by(email=TEST_EMAIL).first()
            assert test_user is not None
            assert test_user.password_hash != "testpass123"
    finally:
        with app.app_context():
            # Delete only the temporary account created by this test run.
            test_user = User.query.filter_by(email=TEST_EMAIL).first()
            if test_user is not None:
                db.session.delete(test_user)
                db.session.commit()
