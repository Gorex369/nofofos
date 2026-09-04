from datetime import date, datetime

from extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    student_id = db.Column(db.String(30), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    branch = db.Column(db.String(100), nullable=True)
    semester = db.Column(db.String(30), nullable=True)
    section = db.Column(db.String(30), nullable=True)
    academic_year = db.Column(db.String(30), nullable=True)
    batch_group = db.Column(db.String(50), nullable=True)
    role = db.Column(db.String(30), nullable=True, default="student")
    faculty_id = db.Column(db.String(50), nullable=True)
    designation = db.Column(db.String(100), nullable=True)

    subjects = db.relationship("Subject", backref="student", lazy=True, cascade="all, delete-orphan")
    attendance_records = db.relationship(
        "Attendance", backref="student", lazy=True, cascade="all, delete-orphan"
    )
    assessments = db.relationship(
        "Assessment", backref="student", lazy=True, cascade="all, delete-orphan"
    )


class Subject(db.Model):
    __tablename__ = "subjects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(20), nullable=False)
    faculty_name = db.Column(db.String(120), nullable=True)
    credits = db.Column(db.Integer, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    classes_held = db.Column(db.Integer, nullable=False, default=0)
    classes_attended = db.Column(db.Integer, nullable=False, default=0)
    record_date = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(10), nullable=True)
    class_type = db.Column(db.String(20), nullable=True)
    topic = db.Column(db.String(255), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)

    subject = db.relationship("Subject", backref="attendance_records")


class Assessment(db.Model):
    __tablename__ = "assessments"

    id = db.Column(db.Integer, primary_key=True)
    assessment_type = db.Column(db.String(50), nullable=False)
    assessment_title = db.Column(db.String(120), nullable=True)
    marks_obtained = db.Column(db.Float, nullable=False)
    maximum_marks = db.Column(db.Float, nullable=False)
    assessment_date = db.Column(db.Date, nullable=False, default=date.today)
    remarks = db.Column(db.String(255), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)

    subject = db.relationship("Subject", backref="assessments")


class AcademicActivity(db.Model):
    __tablename__ = "academic_activities"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=True)
    activity_category = db.Column(db.String(30), nullable=False)
    activity_type = db.Column(db.String(60), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    activity_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(1000), nullable=False)
    organizer = db.Column(db.String(120), nullable=True)
    location = db.Column(db.String(120), nullable=True)
    verification_status = db.Column(db.String(20), nullable=False, default="Pending")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    student = db.relationship("User", backref="academic_activities")
    subject = db.relationship("Subject", backref="academic_activities")


class EvidenceAttachment(db.Model):
    __tablename__ = "evidence_attachments"
    __table_args__ = (
        db.CheckConstraint(
            "((activity_id IS NOT NULL) + (assessment_id IS NOT NULL) + (attendance_id IS NOT NULL)) = 1",
            name="ck_evidence_exactly_one_parent",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("academic_activities.id"), nullable=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessments.id"), nullable=True)
    attendance_id = db.Column(db.Integer, db.ForeignKey("attendance.id"), nullable=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    storage_path = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    verification_status = db.Column(db.String(20), nullable=False, default="Pending")

    student = db.relationship("User", backref="evidence_attachments")
    activity = db.relationship("AcademicActivity", backref="evidence_attachments")
    assessment = db.relationship("Assessment", backref="evidence_attachments")
    attendance = db.relationship("Attendance", backref="evidence_attachments")


class AcademicReview(db.Model):
    __tablename__ = "academic_reviews"
    __table_args__ = (
        db.CheckConstraint(
            "reviewed_marks_obtained >= 0 AND recorded_marks_obtained >= 0",
            name="ck_review_marks_non_negative",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessments.id"), nullable=False)
    recorded_marks_obtained = db.Column(db.Float, nullable=False)
    reviewed_marks_obtained = db.Column(db.Float, nullable=False)
    difference = db.Column(db.Float, nullable=False)
    review_note = db.Column(db.String(1000), nullable=True)
    review_status = db.Column(db.String(30), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    student = db.relationship("User", backref="academic_reviews")
    assessment = db.relationship("Assessment", backref="academic_reviews")


class OfficialTimetable(db.Model):
    __tablename__ = "official_timetables"
    __table_args__ = (
        db.UniqueConstraint(
            "academic_year", "semester", "programme", "section", "batch_group", "version_number",
            name="uq_timetable_applicable_version",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    academic_year = db.Column(db.String(30), nullable=False)
    semester = db.Column(db.String(30), nullable=False)
    programme = db.Column(db.String(100), nullable=False)
    section = db.Column(db.String(30), nullable=False)
    batch_group = db.Column(db.String(50), nullable=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    storage_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(100), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    effective_from = db.Column(db.Date, nullable=False)
    effective_until = db.Column(db.Date, nullable=True)
    version_number = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Draft")
    uploaded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    uploaded_by = db.relationship("User", backref="uploaded_timetables")
    entries = db.relationship("TimetableEntry", backref="timetable", lazy=True, cascade="all, delete-orphan")


class TimetableEntry(db.Model):
    __tablename__ = "timetable_entries"

    id = db.Column(db.Integer, primary_key=True)
    timetable_id = db.Column(db.Integer, db.ForeignKey("official_timetables.id"), nullable=False)
    day_of_week = db.Column(db.String(10), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=True)
    subject_name = db.Column(db.String(120), nullable=False)
    room_lab = db.Column(db.String(80), nullable=True)
    faculty_name = db.Column(db.String(120), nullable=True)
    batch_group = db.Column(db.String(50), nullable=True)

    subject = db.relationship("Subject", backref="timetable_entries")


class FacultyAssignment(db.Model):
    __tablename__ = "faculty_assignments"

    id = db.Column(db.Integer, primary_key=True)
    faculty_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    student_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=True)
    section = db.Column(db.String(30), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    faculty = db.relationship("User", foreign_keys=[faculty_user_id], backref="faculty_assignments")
    student = db.relationship("User", foreign_keys=[student_user_id], backref="assigned_faculty")
    subject = db.relationship("Subject", backref="faculty_assignments")


class VerificationAudit(db.Model):
    __tablename__ = "verification_audits"

    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    actor_role = db.Column(db.String(30), nullable=True)
    target_type = db.Column(db.String(50), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(50), nullable=False)
    note = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    actor = db.relationship("User", backref="verification_audits")


class AttendanceAuthorization(db.Model):
    __tablename__ = "attendance_authorizations"
    __table_args__ = (
        db.UniqueConstraint("activity_id", "faculty_id", name="uq_activity_faculty_authorization"),
    )

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("academic_activities.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    authorization_status = db.Column(db.String(20), nullable=False, default="Pending")
    authorized_attendance_units = db.Column(db.Integer, nullable=True)
    authorization_note = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    activity = db.relationship("AcademicActivity", backref="attendance_authorizations")
    student = db.relationship("User", foreign_keys=[student_id], backref="attendance_authorizations_received")
    faculty = db.relationship("User", foreign_keys=[faculty_id], backref="attendance_authorizations_given")
