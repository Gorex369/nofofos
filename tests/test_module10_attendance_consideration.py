from io import BytesIO
import os

from app import app, db
from models import AcademicActivity, Attendance, AttendanceConsideration, EvidenceAttachment, FacultyAssignment, Subject, User, VerificationAudit


EMAILS = ("module10.student@example.com", "module10.other@example.com", "module10.faculty@example.com", "module10.unassigned@example.com", "module10.coordinator@example.com", "module10.admin@example.com")


def register(client, email, student_id):
    return client.post("/register", data={"full_name": "Module 10 Test", "student_id": student_id, "email": email, "password": "testpass123"})


def login(client, email):
    return client.post("/login", data={"email": email, "password": "testpass123"})


def test_attendance_consideration_credit_is_auditable_and_isolated():
    app.config.update(TESTING=True)
    user_ids = []
    with app.app_context():
        assert not User.query.filter(User.email.in_(EMAILS)).first(), "Temporary Module 10 account already exists."
    client = app.test_client()
    try:
        for index, email in enumerate(EMAILS):
            assert register(client, email, f"M10-{index}").status_code == 302
            with app.app_context(): user_ids.append(User.query.filter_by(email=email).first().id)
        with app.app_context():
            for index, role in ((2, "faculty"), (3, "faculty"), (4, "coordinator"), (5, "admin")):
                db.session.get(User, user_ids[index]).role = role
            db.session.get(User, user_ids[0]).section = "A"
            subject = Subject(name="Module 10 Subject", code="M10-101", user_id=user_ids[0])
            db.session.add(subject); db.session.flush()
            db.session.add(FacultyAssignment(faculty_user_id=user_ids[2], student_user_id=user_ids[0], subject_id=subject.id, section="A"))
            db.session.add_all([Attendance(user_id=user_ids[0], subject_id=subject.id, status="Present"), Attendance(user_id=user_ids[0], subject_id=subject.id, status="Absent")])
            db.session.commit(); subject_id = subject.id
        login(client, EMAILS[0])
        assert client.post("/activities/add", data={"title":"Module 10 Activity","description":"Credit request.","activity_category":"Academic","activity_type":"Workshop","activity_date":"2026-09-06","subject_id":subject_id}).status_code == 302
        with app.app_context(): activity_id = AcademicActivity.query.filter_by(user_id=user_ids[0], title="Module 10 Activity").one().id
        assert client.post(f"/activities/{activity_id}/attendance-consideration", data={"requested_attendance_units":"1","request_note":"Official workshop","proof_file":(BytesIO(b"%PDF-1.7 proof"),"proof.pdf","application/pdf")}, content_type="multipart/form-data").status_code == 302
        with app.app_context():
            request_record = AttendanceConsideration.query.filter_by(activity_id=activity_id).one()
            assert request_record.status == "Pending" and request_record.requested_attendance_units == 1
            assert EvidenceAttachment.query.filter_by(activity_id=activity_id).count() == 1
            assert Attendance.query.filter_by(user_id=user_ids[0]).count() == 2
        client.get("/logout"); login(client, EMAILS[1])
        assert client.post(f"/activities/{activity_id}/attendance-consideration", data={"requested_attendance_units":"1"}).status_code == 404
        client.get("/logout"); login(client, EMAILS[3])
        assert client.post(f"/faculty/activities/{activity_id}/attendance-consideration/grant", data={"authorized_attendance_units":"1"}).status_code == 404
        client.get("/logout"); login(client, EMAILS[4])
        assert client.post(f"/coordinator/activities/{activity_id}/verify").status_code == 302
        client.get("/logout"); login(client, EMAILS[2])
        assert client.post(f"/faculty/activities/{activity_id}/attendance-consideration/reject", data={}).status_code == 400
        assert client.post(f"/faculty/activities/{activity_id}/attendance-consideration/grant", data={"authorized_attendance_units":"1", "note":"Verified attendance credit."}).status_code == 302
        with app.app_context():
            request_record = AttendanceConsideration.query.filter_by(activity_id=activity_id).one()
            assert request_record.status == "Authorized" and request_record.authorized_attendance_units == 1
            assert Attendance.query.filter_by(user_id=user_ids[0]).count() == 2
            assert VerificationAudit.query.filter_by(target_id=activity_id, action="ATTENDANCE_CREDIT_GRANTED").count() == 1
        client.get("/logout"); login(client, EMAILS[0])
        page = client.get(f"/attendance?subject_id={subject_id}")
        assert page.status_code == 200 and b"1 authorized" in page.data and b"100.00%" in page.data
        client.get("/logout"); login(client, EMAILS[2])
        assert client.post(f"/faculty/activities/{activity_id}/attendance-consideration/grant", data={"authorized_attendance_units":"1"}).status_code == 400
    finally:
        with app.app_context():
            for evidence in EvidenceAttachment.query.filter(EvidenceAttachment.user_id.in_(user_ids)).all():
                path = evidence.storage_path; db.session.delete(evidence)
                if os.path.isfile(path): os.remove(path)
            for item in AttendanceConsideration.query.filter(AttendanceConsideration.student_id.in_(user_ids)).all(): db.session.delete(item)
            for audit in VerificationAudit.query.filter(VerificationAudit.actor_user_id.in_(user_ids)).all(): db.session.delete(audit)
            for activity in AcademicActivity.query.filter(AcademicActivity.user_id.in_(user_ids)).all(): db.session.delete(activity)
            for attendance in Attendance.query.filter(Attendance.user_id.in_(user_ids)).all(): db.session.delete(attendance)
            for assignment in FacultyAssignment.query.filter(FacultyAssignment.faculty_user_id.in_(user_ids)).all(): db.session.delete(assignment)
            for subject in Subject.query.filter(Subject.user_id.in_(user_ids)).all(): db.session.delete(subject)
            db.session.flush()
            for user_id in user_ids:
                user = db.session.get(User, user_id)
                if user: db.session.delete(user)
            db.session.commit()
