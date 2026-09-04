"""Explicit development-only provisioning for role demo accounts.

Run with: venv\\Scripts\\python.exe seed_demo_accounts.py
Existing accounts are never overwritten.
"""

from app import app, db
from models import User
from werkzeug.security import generate_password_hash


DEMO_ACCOUNTS = (
    ("demo.faculty@example.com", "Demo Faculty / Student Mentor", "DEMO-FACULTY", "faculty"),
    ("demo.coordinator@example.com", "Demo Society Coordinator", "DEMO-COORDINATOR", "coordinator"),
    ("demo.admin@example.com", "Demo Admin", "DEMO-ADMIN", "admin"),
)
DEMO_PASSWORD = "DemoOnly-2026!"


def provision_demo_accounts():
    created = []
    skipped = []
    with app.app_context():
        for email, full_name, student_id, role in DEMO_ACCOUNTS:
            user = User.query.filter_by(email=email).first()
            if user is not None:
                skipped.append(email)
                continue
            db.session.add(
                User(
                    email=email,
                    full_name=full_name,
                    student_id=student_id,
                    password_hash=generate_password_hash(DEMO_PASSWORD),
                    role=role,
                    faculty_id=student_id if role == "faculty" else None,
                    designation="Development demo account",
                )
            )
            created.append(email)
        db.session.commit()
    return created, skipped


if __name__ == "__main__":
    created, skipped = provision_demo_accounts()
    print("Created:", ", ".join(created) if created else "none")
    print("Already existed and were unchanged:", ", ".join(skipped) if skipped else "none")
    print("Demo password is available only in this development command: DemoOnly-2026!")
