from io import BytesIO
import os

from app import app, db
from models import AcademicActivity, AcademicReview, Assessment, Attendance, AttendanceAuthorization, EvidenceAttachment, FacultyAssignment, OfficialTimetable, Subject, TimetableEntry, User, VerificationAudit


EMAILS = (
    "module8c.student@example.com",
    "module8c.unassigned@example.com",
    "module8c.faculty@example.com",
    "module8c.coordinator@example.com",
    "module8c.admin@example.com",
)


def register(client, email, student_id):
    return client.post("/register", data={"full_name": "Module 8C Test", "student_id": student_id, "email": email, "password": "testpass123"})


def login(client, email):
    return client.post("/login", data={"email": email, "password": "testpass123"})


def test_eca_verification_mentor_authorization_and_timetable_policy():
    app.config.update(TESTING=True)
    user_ids = []
    activity_ids = []
    timetable_ids = []
    evidence_ids = []

    with app.app_context():
        assert not User.query.filter(User.email.in_(EMAILS)).first(), "Temporary Module 8C account already exists; refusing cleanup."

    client = app.test_client()
    assert client.get("/coordinator/activities").status_code == 302
    assert client.get("/faculty/activities").status_code == 302

    try:
        for email, student_id in zip(EMAILS, ("M8C-STUDENT", "M8C-UNASSIGNED", "M8C-FACULTY", "M8C-COORD", "M8C-ADMIN")):
            assert register(client, email, student_id).status_code == 302
            with app.app_context():
                user_ids.append(User.query.filter_by(email=email).first().id)

        with app.app_context():
            student = db.session.get(User, user_ids[0])
            student.branch, student.semester, student.section, student.academic_year = "CSE", "5", "A", "2026-27"
            unassigned = db.session.get(User, user_ids[1])
            unassigned.branch, unassigned.semester, unassigned.section, unassigned.academic_year = "CSE", "5", "B", "2026-27"
            faculty = db.session.get(User, user_ids[2])
            faculty.role = "faculty"
            coordinator = db.session.get(User, user_ids[3])
            coordinator.role = "coordinator"
            admin = db.session.get(User, user_ids[4])
            admin.role = "admin"
            subject = Subject(name="Module 8C Subject", code="M8C-101", user_id=student.id)
            db.session.add(subject)
            db.session.flush()
            db.session.add(FacultyAssignment(faculty_user_id=faculty.id, student_user_id=student.id, subject_id=subject.id, section="A"))
            db.session.commit()
            subject_id = subject.id

        login(client, EMAILS[0])
        assert client.post("/activities/add", data={"title": "Verified ECA", "description": "Temporary verified activity.", "activity_category": "Extra-Curricular", "activity_type": "Society Work", "activity_date": "2026-09-04", "subject_id": subject_id}).status_code == 302
        assert client.post("/activities/add", data={"title": "Rejected ECA", "description": "Temporary rejected activity.", "activity_category": "Extra-Curricular", "activity_type": "Competition", "activity_date": "2026-09-03"}).status_code == 302
        with app.app_context():
            activities = AcademicActivity.query.filter_by(user_id=user_ids[0]).order_by(AcademicActivity.id).all()
            verified_activity_id, rejected_activity_id = [activity.id for activity in activities]
            activity_ids.extend([verified_activity_id, rejected_activity_id])
        assert client.post(f"/coordinator/activities/{verified_activity_id}/verify").status_code == 403
        assert client.post(f"/coordinator/activities/{verified_activity_id}/reject", data={"note": "Student cannot decide."}).status_code == 403
        assert client.post(f"/faculty/activities/{verified_activity_id}/authorize", data={"authorized_attendance_units": "1"}).status_code == 403
        assert client.post(f"/reviews/1/delete").status_code in (302, 404)
        client.get("/logout")

        login(client, EMAILS[3])
        assert client.get(f"/coordinator/activities/{verified_activity_id}").status_code == 200
        assert client.post(f"/coordinator/activities/{verified_activity_id}/verify").status_code == 302
        with app.app_context():
            activity = db.session.get(AcademicActivity, verified_activity_id)
            assert activity.verification_status == "Verified"
            audit = VerificationAudit.query.filter_by(target_id=verified_activity_id, action="ACTIVITY_VERIFIED").first()
            assert audit is not None and audit.actor_role == "coordinator"
        assert client.post(f"/coordinator/activities/{rejected_activity_id}/reject").status_code == 400
        assert client.post(f"/coordinator/activities/{rejected_activity_id}/reject", data={"note": "Evidence needs clarification."}).status_code == 302
        with app.app_context():
            assert db.session.get(AcademicActivity, rejected_activity_id).verification_status == "Rejected"
            assert VerificationAudit.query.filter_by(target_id=rejected_activity_id, action="ACTIVITY_REJECTED").count() == 1
        client.get("/logout")

        login(client, EMAILS[2])
        assert client.get("/faculty/activities").status_code == 200
        assert client.get(f"/faculty/activities/{verified_activity_id}").status_code == 200
        assert client.get(f"/faculty/activities/{rejected_activity_id}").status_code == 404
        assert client.post(f"/faculty/activities/{verified_activity_id}/authorize", data={"authorized_attendance_units": "2", "note": "Considered by assigned mentor."}).status_code == 302
        with app.app_context():
            authorization = AttendanceAuthorization.query.filter_by(activity_id=verified_activity_id, faculty_id=user_ids[2]).first()
            assert authorization.authorization_status == "Authorized"
            assert VerificationAudit.query.filter_by(target_id=verified_activity_id, action="ATTENDANCE_CONSIDERATION_AUTHORIZED").count() == 1
            assert db.session.get(AcademicActivity, verified_activity_id).verification_status == "Verified"
            assert Attendance.query.filter_by(user_id=user_ids[0]).count() == 0
        assert client.post(f"/faculty/activities/{verified_activity_id}/reject", data={"note": "Not authorized in this review."}).status_code == 302
        client.get("/logout")

        login(client, EMAILS[1])
        assert client.get(f"/faculty/activities/{verified_activity_id}").status_code == 403
        client.get("/logout")

        login(client, EMAILS[3])
        assert client.post("/subjects/add", data={"name": "Coordinator Subject", "code": "M8C-COORD"}).status_code == 302
        client.get("/logout")

        login(client, EMAILS[0])
        with app.app_context():
            attendance_total = Attendance.query.filter_by(user_id=user_ids[0]).count()
        assert client.post(f"/activities/{verified_activity_id}/evidence/add", data={"evidence_file": (BytesIO(b"%PDF-1.7 evidence"), "eca.pdf", "application/pdf")}, content_type="multipart/form-data").status_code == 302
        with app.app_context():
            evidence = EvidenceAttachment.query.filter_by(activity_id=verified_activity_id).first()
            evidence_ids.append(evidence.id)
        client.get("/logout")

        login(client, EMAILS[3])
        assert client.get(f"/coordinator/activities/{verified_activity_id}/evidence/{evidence_ids[0]}").status_code == 200
        assert client.get(f"/coordinator/activities/{verified_activity_id}/evidence/{evidence_ids[0]}/download").status_code == 200
        client.get("/logout")

        login(client, EMAILS[2])
        timetable_data = {"academic_year": "2026-27", "semester": "5", "programme": "CSE", "section": "A", "batch_group": "G1", "effective_from": "2026-01-01", "effective_until": "2027-12-31"}
        timetable_data["timetable_file"] = (BytesIO(b"%PDF-1.7 timetable"), "draft.pdf", "application/pdf")
        assert client.post("/coordinator/timetables/add", data=timetable_data, content_type="multipart/form-data").status_code == 302
        with app.app_context():
            timetable = OfficialTimetable.query.filter_by(original_filename="draft.pdf").first()
            timetable_id = timetable.id
            timetable_ids.append(timetable_id)
        assert client.post(f"/coordinator/timetables/{timetable_id}/entries/add", data={"day_of_week": "Monday", "start_time": "09:00", "end_time": "10:00", "subject_name": "Draft Class"}).status_code == 302
        client.get("/logout")

        login(client, EMAILS[2])
        assert client.get(f"/coordinator/timetables/{timetable_id}").status_code == 200
        assert client.post(f"/coordinator/timetables/{timetable_id}/publish").status_code == 403
        assert client.post(f"/coordinator/timetables/{timetable_id}/archive").status_code == 403
        client.get("/logout")

        login(client, EMAILS[3])
        assert client.get(f"/coordinator/timetables/{timetable_id}").status_code == 200
        assert client.post(f"/coordinator/timetables/{timetable_id}/publish").status_code == 302
        client.get("/logout")

        login(client, EMAILS[0])
        with app.app_context():
            assert Attendance.query.filter_by(user_id=user_ids[0]).count() == attendance_total
        client.get("/logout")
    finally:
        with app.app_context():
            for review in AcademicReview.query.filter(AcademicReview.user_id.in_(user_ids)).all(): db.session.delete(review)
            for authorization in AttendanceAuthorization.query.filter(AttendanceAuthorization.student_id.in_(user_ids)).all(): db.session.delete(authorization)
            for audit in VerificationAudit.query.filter(VerificationAudit.actor_user_id.in_(user_ids)).all(): db.session.delete(audit)
            for evidence in EvidenceAttachment.query.filter(EvidenceAttachment.user_id.in_(user_ids)).all():
                path = evidence.storage_path
                db.session.delete(evidence)
                if os.path.isfile(path) and os.path.commonpath([os.path.abspath(app.config["EVIDENCE_UPLOAD_DIR"]), os.path.abspath(path)]) == os.path.abspath(app.config["EVIDENCE_UPLOAD_DIR"]): os.remove(path)
            for timetable in OfficialTimetable.query.filter(OfficialTimetable.uploaded_by_id.in_(user_ids)).all():
                path = timetable.storage_path
                db.session.delete(timetable)
                if os.path.isfile(path) and os.path.commonpath([os.path.abspath(app.config["TIMETABLE_UPLOAD_DIR"]), os.path.abspath(path)]) == os.path.abspath(app.config["TIMETABLE_UPLOAD_DIR"]): os.remove(path)
            for activity in AcademicActivity.query.filter(AcademicActivity.user_id.in_(user_ids)).all(): db.session.delete(activity)
            for attendance in Attendance.query.filter(Attendance.user_id.in_(user_ids)).all(): db.session.delete(attendance)
            for assessment in Assessment.query.filter(Assessment.user_id.in_(user_ids)).all(): db.session.delete(assessment)
            for subject in Subject.query.filter(Subject.user_id.in_(user_ids)).all(): db.session.delete(subject)
            for assignment in FacultyAssignment.query.filter(FacultyAssignment.faculty_user_id.in_(user_ids)).all(): db.session.delete(assignment)
            for user_id in user_ids:
                user = db.session.get(User, user_id)
                if user is not None: db.session.delete(user)
            db.session.commit()
