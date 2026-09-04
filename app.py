import os
import uuid
from functools import wraps
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Flask, flash, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import inspect, or_, text
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import RequestEntityTooLarge

from extensions import db
from models import AcademicActivity, AcademicReview, Assessment, Attendance, AttendanceAuthorization, EvidenceAttachment, FacultyAssignment, OfficialTimetable, Subject, TimetableEntry, User, VerificationAudit

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "student-tracker-development-key")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
    os.path.dirname(__file__), "database", "academic_records.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["ACADEMIC_GOOD_THRESHOLD"] = 75.0
app.config["ACTIVITY_CATEGORIES"] = {"Academic", "Extra-Curricular"}
app.config["ACTIVITY_TYPES"] = {
    "Project",
    "Seminar",
    "Presentation",
    "Certification",
    "Society Work",
    "College Event",
    "Competition",
    "Workshop",
    "Official Student Activity",
    "Other",
}
app.config["ACTIVITY_VERIFICATION_STATUSES"] = {"Pending", "Verified", "Rejected"}
app.config["REVIEW_STATUSES"] = {"No Difference", "Difference Found", "Needs Review"}
app.config["TIMETABLE_DAYS"] = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
app.config["TIMETABLE_STATUSES"] = {"Draft", "Published", "Archived"}
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
app.config["EVIDENCE_UPLOAD_DIR"] = os.path.join(os.path.dirname(__file__), "evidence_uploads")
app.config["TIMETABLE_UPLOAD_DIR"] = os.path.join(os.path.dirname(__file__), "timetable_uploads")
app.config["TIMETABLE_MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["EVIDENCE_MIME_TYPES"] = {
    ".pdf": ("application/pdf", b"%PDF"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
}
os.makedirs(os.path.join(os.path.dirname(__file__), "database"), exist_ok=True)

db.init_app(app)
os.makedirs(app.config["EVIDENCE_UPLOAD_DIR"], exist_ok=True)
os.makedirs(app.config["TIMETABLE_UPLOAD_DIR"], exist_ok=True)


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def coordinator_required(view):
    @wraps(view)
    @login_required
    def wrapped_view(*args, **kwargs):
        user = db.session.get(User, session["user_id"])
        if user is None or user.role not in {"coordinator", "admin"}:
            return "Coordinator authorization required.", 403
        return view(*args, **kwargs)

    return wrapped_view


def timetable_manager_required(view):
    @wraps(view)
    @login_required
    def wrapped_view(*args, **kwargs):
        user = db.session.get(User, session["user_id"])
        if user is None or user.role not in {"faculty", "coordinator", "admin"}:
            return "Timetable management authorization required.", 403
        return view(*args, **kwargs)

    return wrapped_view


def role_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped_view(*args, **kwargs):
            user = db.session.get(User, session["user_id"])
            if user is None or user.role not in allowed_roles:
                return "You are not authorized to access this page.", 403
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def initialize_database():
    db.create_all()

    # Add only new nullable columns so existing SQLite records remain valid.
    new_columns = {
        "users": {
            "branch": "VARCHAR(100)",
            "semester": "VARCHAR(30)",
            "section": "VARCHAR(30)",
            "academic_year": "VARCHAR(30)",
            "batch_group": "VARCHAR(50)",
            "role": "VARCHAR(30)",
            "faculty_id": "VARCHAR(50)",
            "designation": "VARCHAR(100)",
        },
        "subjects": {
            "faculty_name": "VARCHAR(120)",
            "credits": "INTEGER",
        },
        "attendance": {
            "status": "VARCHAR(10)",
            "class_type": "VARCHAR(20)",
            "topic": "VARCHAR(255)",
        },
        "assessments": {
            "assessment_title": "VARCHAR(120)",
            "remarks": "VARCHAR(255)",
        },
        "verification_audits": {
            "actor_role": "VARCHAR(30)",
        },
    }
    inspector = inspect(db.engine)
    for table_name, columns in new_columns.items():
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                db.session.execute(
                    text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                )
    db.session.commit()


with app.app_context():
    initialize_database()


@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        student_id = request.form.get("student_id", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not all([full_name, student_id, email, password]):
            flash("All fields are required.", "danger")
            return render_template("register.html")

        if User.query.filter((User.email == email) | (User.student_id == student_id)).first():
            flash("An account with that email or student ID already exists.", "danger")
            return render_template("register.html")

        user = User(
            full_name=full_name,
            student_id=student_id,
            email=email,
            password_hash=generate_password_hash(password),
            role="student",
        )
        db.session.add(user)
        db.session.commit()
        flash("Registration successful. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user is None or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "danger")
            return render_template("login.html")

        session.clear()
        session["user_id"] = user.id
        session["user_role"] = user.role or "student"
        session["is_coordinator"] = user.role in {"coordinator", "admin"}
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    user = db.get_or_404(User, session["user_id"])
    subjects = Subject.query.filter_by(user_id=user.id).order_by(Subject.name).all()
    attendance_count = Attendance.query.filter_by(user_id=user.id).count()
    assessment_count = Assessment.query.filter_by(user_id=user.id).count()
    attendance_summaries = []
    for subject in subjects:
        records = Attendance.query.filter_by(user_id=user.id, subject_id=subject.id).all()
        attendance_summaries.append({"subject": subject, "summary": attendance_summary(records)})
    overall_attendance = attendance_summary(Attendance.query.filter_by(user_id=user.id).all())
    assessment_summaries = []
    academic_overview = []
    for subject in subjects:
        assessment_records = Assessment.query.filter_by(
            user_id=user.id, subject_id=subject.id
        ).all()
        assessment_result = assessment_summary(assessment_records)
        assessment_summaries.append({"subject": subject, "summary": assessment_result})
        attendance_result = next(
            item["summary"] for item in attendance_summaries if item["subject"].id == subject.id
        )
        academic_overview.append(
            {
                "subject": subject,
                "attendance": attendance_result,
                "assessment": assessment_result,
            }
        )
    overall_assessment = assessment_summary(Assessment.query.filter_by(user_id=user.id).all())
    recent_activities = AcademicActivity.query.filter_by(user_id=user.id).order_by(
        AcademicActivity.activity_date.desc(), AcademicActivity.id.desc()
    ).limit(5).all()
    activity_count = AcademicActivity.query.filter_by(user_id=user.id).count()
    applicable_timetable = find_applicable_timetable(user)
    today_entries = []
    if applicable_timetable:
        today_name = date.today().strftime("%A")
        today_entries = sorted(
            [entry for entry in applicable_timetable.entries if entry.day_of_week == today_name and (entry.batch_group is None or entry.batch_group == user.batch_group)],
            key=lambda entry: entry.start_time,
        )
    return render_template(
        "dashboard.html",
        user=user,
        subjects=subjects,
        attendance_count=attendance_count,
        assessment_count=assessment_count,
        assessment_summaries=assessment_summaries,
        overall_assessment=overall_assessment,
        attendance_summaries=attendance_summaries,
        overall_attendance=overall_attendance,
        academic_overview=academic_overview,
        status_threshold=app.config["ACADEMIC_GOOD_THRESHOLD"],
        recent_activities=recent_activities,
        activity_count=activity_count,
        today_entries=today_entries,
        today_name=date.today().strftime("%A"),
        current_time=datetime.now().strftime("%H:%M"),
    )


@app.route("/faculty/dashboard")
@role_required("faculty")
def faculty_dashboard():
    assignments = FacultyAssignment.query.filter_by(
        faculty_user_id=session["user_id"]
    ).order_by(FacultyAssignment.created_at.desc()).all()
    return render_template("faculty_dashboard.html", user=db.session.get(User, session["user_id"]), assignments=assignments)


@app.route("/coordinator/dashboard")
@role_required("coordinator", "admin")
def coordinator_dashboard():
    pending_activities = AcademicActivity.query.filter_by(
        verification_status="Pending"
    ).order_by(AcademicActivity.activity_date.desc()).all()
    return render_template(
        "coordinator_dashboard.html",
        user=db.session.get(User, session["user_id"]),
        pending_activities=pending_activities,
    )


@app.route("/coordinator/activities")
@role_required("coordinator", "admin")
def coordinator_activities():
    activities = AcademicActivity.query.order_by(
        AcademicActivity.activity_date.desc(), AcademicActivity.id.desc()
    ).all()
    return render_template("coordinator_activities.html", activities=activities)


@app.route("/admin/dashboard")
@role_required("admin")
def admin_dashboard():
    users = User.query.order_by(User.role, User.full_name).all()
    return render_template("admin_dashboard.html", user=db.session.get(User, session["user_id"]), users=users)


@app.route("/coordinator/activities/<int:activity_id>")
@role_required("coordinator", "admin")
def coordinator_activity_detail(activity_id):
    activity = db.get_or_404(AcademicActivity, activity_id)
    audits = VerificationAudit.query.filter_by(target_type="AcademicActivity", target_id=activity.id).order_by(VerificationAudit.created_at.desc()).all()
    return render_template("coordinator_activity_detail.html", activity=activity, audits=audits)


@app.route("/coordinator/activities/<int:activity_id>/verify", methods=["POST"])
@role_required("coordinator", "admin")
def verify_activity(activity_id):
    activity = AcademicActivity.query.filter_by(id=activity_id, verification_status="Pending").first_or_404()
    activity.verification_status = "Verified"
    db.session.add(VerificationAudit(
        actor_user_id=session["user_id"], actor_role=db.session.get(User, session["user_id"]).role,
        target_type="AcademicActivity", target_id=activity.id, action="ACTIVITY_VERIFIED",
        note=request.form.get("note", "").strip() or None,
    ))
    db.session.commit()
    flash("Activity verified.", "success")
    return redirect(url_for("coordinator_activity_detail", activity_id=activity.id))


@app.route("/coordinator/activities/<int:activity_id>/reject", methods=["POST"])
@role_required("coordinator", "admin")
def reject_activity(activity_id):
    activity = AcademicActivity.query.filter_by(id=activity_id, verification_status="Pending").first_or_404()
    note = request.form.get("note", "").strip()
    if not note or len(note) > 1000:
        return render_template("coordinator_activity_detail.html", activity=activity, audits=[], form_error="A rejection reason is required and must be 1000 characters or fewer."), 400
    activity.verification_status = "Rejected"
    db.session.add(VerificationAudit(
        actor_user_id=session["user_id"], actor_role=db.session.get(User, session["user_id"]).role,
        target_type="AcademicActivity", target_id=activity.id, action="ACTIVITY_REJECTED", note=note,
    ))
    db.session.commit()
    flash("Activity rejected.", "success")
    return redirect(url_for("coordinator_activity_detail", activity_id=activity.id))


def assigned_verified_activity_query(faculty_user_id):
    return AcademicActivity.query.join(
        FacultyAssignment, FacultyAssignment.student_user_id == AcademicActivity.user_id
    ).filter(
        FacultyAssignment.faculty_user_id == faculty_user_id,
        AcademicActivity.verification_status == "Verified",
        or_(FacultyAssignment.subject_id.is_(None), FacultyAssignment.subject_id == AcademicActivity.subject_id),
        or_(FacultyAssignment.section.is_(None), FacultyAssignment.section == User.section),
    ).distinct()


@app.route("/faculty/activities")
@role_required("faculty")
def faculty_activities():
    activities = assigned_verified_activity_query(session["user_id"]).order_by(AcademicActivity.activity_date.desc()).all()
    return render_template("faculty_activities.html", activities=activities)


@app.route("/faculty/activities/<int:activity_id>")
@role_required("faculty")
def faculty_activity_detail(activity_id):
    activity = assigned_verified_activity_query(session["user_id"]).filter(AcademicActivity.id == activity_id).first_or_404()
    authorizations = AttendanceAuthorization.query.filter_by(activity_id=activity.id, faculty_id=session["user_id"]).order_by(AttendanceAuthorization.created_at.desc()).all()
    audits = VerificationAudit.query.filter_by(target_type="AcademicActivity", target_id=activity.id).order_by(VerificationAudit.created_at.desc()).all()
    return render_template("faculty_activity_detail.html", activity=activity, authorizations=authorizations, audits=audits)


def faculty_authorized_activity(activity_id):
    return assigned_verified_activity_query(session["user_id"]).filter(AcademicActivity.id == activity_id).first_or_404()


def parse_authorization_units(form):
    value = form.get("authorized_attendance_units", "").strip()
    try:
        units = int(value)
    except ValueError:
        return None
    return units if units >= 0 else None


@app.route("/faculty/activities/<int:activity_id>/authorize", methods=["POST"])
@role_required("faculty")
def authorize_activity_attendance(activity_id):
    activity = faculty_authorized_activity(activity_id)
    units = parse_authorization_units(request.form)
    note = request.form.get("note", "").strip() or None
    if units is None or len(note or "") > 1000:
        return render_template("faculty_activity_detail.html", activity=activity, authorizations=[], audits=[], form_error="Authorized attendance units must be a non-negative whole number; note must be 1000 characters or fewer."), 400
    authorization = AttendanceAuthorization.query.filter_by(activity_id=activity.id, faculty_id=session["user_id"]).first()
    if authorization is None:
        authorization = AttendanceAuthorization(activity_id=activity.id, student_id=activity.user_id, faculty_id=session["user_id"])
        db.session.add(authorization)
    authorization.authorization_status = "Authorized"
    authorization.authorized_attendance_units = units
    authorization.authorization_note = note
    db.session.add(VerificationAudit(
        actor_user_id=session["user_id"], actor_role="faculty", target_type="AcademicActivity", target_id=activity.id,
        action="ATTENDANCE_CONSIDERATION_AUTHORIZED", note=note,
    ))
    db.session.commit()
    flash("Attendance consideration authorization recorded. Attendance was not changed.", "success")
    return redirect(url_for("faculty_activity_detail", activity_id=activity.id))


@app.route("/faculty/activities/<int:activity_id>/reject", methods=["POST"])
@role_required("faculty")
def reject_activity_attendance(activity_id):
    activity = faculty_authorized_activity(activity_id)
    note = request.form.get("note", "").strip()
    if not note or len(note) > 1000:
        return render_template("faculty_activity_detail.html", activity=activity, authorizations=[], audits=[], form_error="A reason is required and must be 1000 characters or fewer."), 400
    authorization = AttendanceAuthorization.query.filter_by(activity_id=activity.id, faculty_id=session["user_id"]).first()
    if authorization is None:
        authorization = AttendanceAuthorization(activity_id=activity.id, student_id=activity.user_id, faculty_id=session["user_id"])
        db.session.add(authorization)
    authorization.authorization_status = "Rejected"
    authorization.authorization_note = note
    db.session.add(VerificationAudit(
        actor_user_id=session["user_id"], actor_role="faculty", target_type="AcademicActivity", target_id=activity.id,
        action="ATTENDANCE_CONSIDERATION_REJECTED", note=note,
    ))
    db.session.commit()
    flash("Attendance consideration decision recorded.", "success")
    return redirect(url_for("faculty_activity_detail", activity_id=activity.id))


@app.route("/faculty/activities/<int:activity_id>/evidence/<int:evidence_id>")
@role_required("faculty")
def faculty_evidence_detail(activity_id, evidence_id):
    activity = faculty_authorized_activity(activity_id)
    evidence = EvidenceAttachment.query.filter_by(id=evidence_id, activity_id=activity.id).first_or_404()
    return render_template("faculty_evidence_detail.html", activity=activity, evidence=evidence)


@app.route("/faculty/activities/<int:activity_id>/evidence/<int:evidence_id>/download")
@role_required("faculty")
def faculty_evidence_download(activity_id, evidence_id):
    activity = faculty_authorized_activity(activity_id)
    evidence = EvidenceAttachment.query.filter_by(id=evidence_id, activity_id=activity.id).first_or_404()
    path = evidence_path(evidence)
    if path is None or not os.path.isfile(path):
        return "Evidence file not found.", 404
    return send_file(path, mimetype=evidence.mime_type, as_attachment=False, download_name=evidence.original_filename)


@app.route("/coordinator/activities/<int:activity_id>/evidence/<int:evidence_id>")
@role_required("faculty", "coordinator", "admin")
def coordinator_evidence_detail(activity_id, evidence_id):
    if db.session.get(User, session["user_id"]).role == "faculty":
        activity = faculty_authorized_activity(activity_id)
    else:
        activity = db.get_or_404(AcademicActivity, activity_id)
    evidence = EvidenceAttachment.query.filter_by(id=evidence_id, activity_id=activity.id).first_or_404()
    return render_template("coordinator_evidence_detail.html", activity=activity, evidence=evidence)


@app.route("/coordinator/activities/<int:activity_id>/evidence/<int:evidence_id>/download")
@role_required("faculty", "coordinator", "admin")
def coordinator_evidence_download(activity_id, evidence_id):
    if db.session.get(User, session["user_id"]).role == "faculty":
        activity = faculty_authorized_activity(activity_id)
    else:
        activity = db.get_or_404(AcademicActivity, activity_id)
    evidence = EvidenceAttachment.query.filter_by(id=evidence_id, activity_id=activity.id).first_or_404()
    path = evidence_path(evidence)
    if path is None or not os.path.isfile(path):
        return "Evidence file not found.", 404
    return send_file(path, mimetype=evidence.mime_type, as_attachment=False, download_name=evidence.original_filename)


def find_applicable_timetable(user, academic_year=None, semester=None, programme=None, section=None, batch_group=None):
    academic_year = academic_year if academic_year is not None else user.academic_year
    semester = semester if semester is not None else user.semester
    programme = programme if programme is not None else user.branch
    section = section if section is not None else user.section
    batch_group = batch_group if batch_group is not None else user.batch_group
    if not all([academic_year, semester, programme, section]):
        return None
    query = OfficialTimetable.query.filter_by(
        academic_year=academic_year,
        semester=semester,
        programme=programme,
        section=section,
        status="Published",
    ).filter(
        OfficialTimetable.effective_from <= date.today(),
        or_(OfficialTimetable.effective_until.is_(None), OfficialTimetable.effective_until >= date.today()),
        or_(OfficialTimetable.batch_group.is_(None), OfficialTimetable.batch_group == batch_group),
    )
    return query.order_by(OfficialTimetable.version_number.desc(), OfficialTimetable.uploaded_at.desc()).first()


def timetable_file_info(upload):
    if upload is None or not upload.filename:
        return None, "Please choose an official PDF timetable."
    original_filename = upload.filename.replace("\\", "/").rsplit("/", 1)[-1]
    if os.path.splitext(original_filename.lower())[1] != ".pdf":
        return None, "Only PDF timetable documents are supported."
    content = upload.stream.read(app.config["TIMETABLE_MAX_CONTENT_LENGTH"] + 1)
    upload.stream.seek(0)
    if len(content) > app.config["TIMETABLE_MAX_CONTENT_LENGTH"]:
        return None, "The timetable document is too large. The maximum size is 10 MB."
    if upload.mimetype.lower() != "application/pdf" or not content.startswith(b"%PDF"):
        return None, "The uploaded file is not a valid PDF."
    return {"original_filename": original_filename, "file_size": len(content)}, None


def parse_timetable_metadata(form):
    values = {field: form.get(field, "").strip() for field in ("academic_year", "semester", "programme", "section", "batch_group")}
    values["batch_group"] = values["batch_group"] or None
    values["effective_from"] = form.get("effective_from", "").strip()
    values["effective_until"] = form.get("effective_until", "").strip() or None
    errors = []
    if not all(values[field] for field in ("academic_year", "semester", "programme", "section", "effective_from")):
        errors.append("Academic year, semester, programme, section, and effective from are required.")
    try:
        values["effective_from"] = datetime.strptime(values["effective_from"], "%Y-%m-%d").date()
        values["effective_until"] = datetime.strptime(values["effective_until"], "%Y-%m-%d").date() if values["effective_until"] else None
    except ValueError:
        errors.append("Enter valid effective dates.")
    if values.get("effective_until") and values.get("effective_from") and values["effective_until"] < values["effective_from"]:
        errors.append("Effective until must not be before effective from.")
    return values, errors


def timetable_form_context(timetable=None, form_error=None):
    return {"timetable": timetable, "form_error": form_error, "today": date.today().isoformat()}


def parse_entry_form(form):
    values = {field: form.get(field, "").strip() or None for field in ("day_of_week", "start_time", "end_time", "subject_name", "room_lab", "faculty_name", "batch_group")}
    errors = []
    if not all(values[field] for field in ("day_of_week", "start_time", "end_time", "subject_name")):
        errors.append("Day, start time, end time, and subject are required.")
    if values["day_of_week"] not in app.config["TIMETABLE_DAYS"]:
        errors.append("Choose a valid day.")
    try:
        start = datetime.strptime(values["start_time"] or "", "%H:%M").time()
        end = datetime.strptime(values["end_time"] or "", "%H:%M").time()
        if end <= start:
            errors.append("End time must be after start time.")
    except ValueError:
        errors.append("Enter valid start and end times.")
    return values, errors


@app.route("/timetable")
@login_required
def student_timetable():
    user = db.session.get(User, session["user_id"])
    timetable = find_applicable_timetable(user)
    entries = sorted(
        [entry for entry in timetable.entries if entry.batch_group is None or entry.batch_group == user.batch_group],
        key=lambda entry: (app.config["TIMETABLE_DAYS"].index(entry.day_of_week), entry.start_time),
    ) if timetable else []
    return render_template("timetable.html", timetable=timetable, entries=entries, user=user, days=app.config["TIMETABLE_DAYS"], today_name=date.today().strftime("%A"))


@app.route("/timetable/document")
@login_required
def download_student_timetable():
    user = db.session.get(User, session["user_id"])
    timetable = find_applicable_timetable(user)
    if timetable is None:
        return "No official timetable is currently available for your academic details.", 404
    return send_timetable_file(timetable)


def send_timetable_file(timetable):
    upload_dir = os.path.abspath(app.config["TIMETABLE_UPLOAD_DIR"])
    path = os.path.abspath(os.path.join(upload_dir, timetable.stored_filename))
    if os.path.commonpath([upload_dir, path]) != upload_dir or not os.path.isfile(path):
        return "Timetable document not found.", 404
    return send_file(path, mimetype=timetable.file_type, as_attachment=False, download_name=timetable.original_filename)


def faculty_can_manage_combination(combination, faculty_user_id):
    assignment_query = FacultyAssignment.query.filter_by(faculty_user_id=faculty_user_id)
    assignment_query = assignment_query.filter(
        or_(FacultyAssignment.section.is_(None), FacultyAssignment.section == combination["section"])
    )
    assignments = assignment_query.all()
    if not assignments:
        return False
    for assignment in assignments:
        if assignment.student.branch and assignment.student.branch != combination["programme"]:
            continue
        if assignment.student.semester and assignment.student.semester != combination["semester"]:
            continue
        if assignment.student.academic_year and assignment.student.academic_year != combination["academic_year"]:
            continue
        if combination["batch_group"] and assignment.student.batch_group and assignment.student.batch_group != combination["batch_group"]:
            continue
        return True
    return False


def faculty_can_manage_timetable(timetable, faculty_user_id):
    combination = {
        "academic_year": timetable.academic_year,
        "semester": timetable.semester,
        "programme": timetable.programme,
        "section": timetable.section,
        "batch_group": timetable.batch_group,
    }
    return faculty_can_manage_combination(combination, faculty_user_id)


def timetable_can_be_managed(timetable):
    user = db.session.get(User, session["user_id"])
    return user.role in {"coordinator", "admin"} or (
        user.role == "faculty" and faculty_can_manage_timetable(timetable, user.id)
    )


@app.route("/coordinator/timetables")
@coordinator_required
def manage_timetables():
    user = db.session.get(User, session["user_id"])
    timetables = OfficialTimetable.query.order_by(OfficialTimetable.uploaded_at.desc()).all()
    if user.role == "faculty":
        timetables = [timetable for timetable in timetables if faculty_can_manage_timetable(timetable, user.id)]
    return render_template("manage_timetables.html", timetables=timetables)


@app.route("/coordinator/timetables/add", methods=["GET", "POST"])
@timetable_manager_required
def add_timetable():
    if request.method == "GET":
        return render_template("timetable_form.html", **timetable_form_context())
    values, errors = parse_timetable_metadata(request.form)
    file_info, file_error = timetable_file_info(request.files.get("timetable_file"))
    if file_error:
        errors.append(file_error)
    if errors:
        return render_template("timetable_form.html", **timetable_form_context(form_error=" ".join(errors)))
    combination = {field: values[field] for field in ("academic_year", "semester", "programme", "section", "batch_group")}
    if db.session.get(User, session["user_id"]).role == "faculty" and not faculty_can_manage_combination(combination, session["user_id"]):
        return render_template("timetable_form.html", **timetable_form_context(form_error="You are not assigned to manage this timetable combination."))
    latest = OfficialTimetable.query.filter_by(**combination).order_by(OfficialTimetable.version_number.desc()).first()
    stored_filename = f"{uuid.uuid4().hex}.pdf"
    storage_path = os.path.abspath(os.path.join(app.config["TIMETABLE_UPLOAD_DIR"], stored_filename))
    try:
        request.files["timetable_file"].save(storage_path)
        timetable = OfficialTimetable(
            **combination, original_filename=file_info["original_filename"], stored_filename=stored_filename,
            storage_path=storage_path, file_type="application/pdf", file_size=file_info["file_size"],
            effective_from=values["effective_from"], effective_until=values["effective_until"],
            version_number=(latest.version_number + 1 if latest else 1), status="Draft", uploaded_by_id=session["user_id"],
        )
        db.session.add(timetable)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if os.path.isfile(storage_path):
            os.remove(storage_path)
        raise
    flash("Timetable uploaded as a draft.", "success")
    return redirect(url_for("manage_timetable_detail", timetable_id=timetable.id))


@app.route("/coordinator/timetables/<int:timetable_id>")
@timetable_manager_required
def manage_timetable_detail(timetable_id):
    timetable = db.get_or_404(OfficialTimetable, timetable_id)
    if not timetable_can_be_managed(timetable):
        return "Timetable management authorization required.", 403
    return render_template(
        "manage_timetable_detail.html",
        timetable=timetable,
        user_role=db.session.get(User, session["user_id"]).role,
    )


@app.route("/coordinator/timetables/<int:timetable_id>/document")
@timetable_manager_required
def download_management_timetable(timetable_id):
    timetable = db.get_or_404(OfficialTimetable, timetable_id)
    if not timetable_can_be_managed(timetable):
        return "Timetable management authorization required.", 403
    return send_timetable_file(timetable)


@app.route("/coordinator/timetables/<int:timetable_id>/publish", methods=["POST"])
@coordinator_required
def publish_timetable(timetable_id):
    timetable = db.get_or_404(OfficialTimetable, timetable_id)
    OfficialTimetable.query.filter_by(
        academic_year=timetable.academic_year, semester=timetable.semester, programme=timetable.programme,
        section=timetable.section, batch_group=timetable.batch_group, status="Published",
    ).update({"status": "Archived"}, synchronize_session=False)
    timetable.status = "Published"
    db.session.commit()
    flash("Timetable published; the previous active version was archived.", "success")
    return redirect(url_for("manage_timetable_detail", timetable_id=timetable.id))


@app.route("/coordinator/timetables/<int:timetable_id>/archive", methods=["POST"])
@coordinator_required
def archive_timetable(timetable_id):
    timetable = db.get_or_404(OfficialTimetable, timetable_id)
    timetable.status = "Archived"
    db.session.commit()
    flash("Timetable archived.", "success")
    return redirect(url_for("manage_timetables"))


@app.route("/coordinator/timetables/<int:timetable_id>/entries/add", methods=["GET", "POST"])
@timetable_manager_required
def add_timetable_entry(timetable_id):
    timetable = db.get_or_404(OfficialTimetable, timetable_id)
    if not timetable_can_be_managed(timetable) or (db.session.get(User, session["user_id"]).role == "faculty" and timetable.status != "Draft"):
        return "Timetable management authorization required.", 403
    if request.method == "GET":
        return render_template("timetable_entry_form.html", timetable=timetable, entry=None, form_error=None, days=app.config["TIMETABLE_DAYS"])
    values, errors = parse_entry_form(request.form)
    if errors:
        return render_template("timetable_entry_form.html", timetable=timetable, entry=None, form_error=" ".join(errors), days=app.config["TIMETABLE_DAYS"])
    entry = TimetableEntry(timetable_id=timetable.id, **values)
    db.session.add(entry)
    db.session.commit()
    return redirect(url_for("manage_timetable_detail", timetable_id=timetable.id))


@app.route("/coordinator/timetables/<int:timetable_id>/entries/<int:entry_id>/edit", methods=["GET", "POST"])
@timetable_manager_required
def edit_timetable_entry(timetable_id, entry_id):
    timetable = db.get_or_404(OfficialTimetable, timetable_id)
    if not timetable_can_be_managed(timetable) or (db.session.get(User, session["user_id"]).role == "faculty" and timetable.status != "Draft"):
        return "Timetable management authorization required.", 403
    entry = TimetableEntry.query.filter_by(id=entry_id, timetable_id=timetable.id).first_or_404()
    if request.method == "POST":
        values, errors = parse_entry_form(request.form)
        if errors:
            return render_template("timetable_entry_form.html", timetable=timetable, entry=entry, form_error=" ".join(errors), days=app.config["TIMETABLE_DAYS"])
        for field, value in values.items():
            setattr(entry, field, value)
        db.session.commit()
        return redirect(url_for("manage_timetable_detail", timetable_id=timetable.id))
    return render_template("timetable_entry_form.html", timetable=timetable, entry=entry, form_error=None, days=app.config["TIMETABLE_DAYS"])


@app.route("/coordinator/timetables/<int:timetable_id>/entries/<int:entry_id>/delete", methods=["POST"])
@timetable_manager_required
def delete_timetable_entry(timetable_id, entry_id):
    timetable = db.get_or_404(OfficialTimetable, timetable_id)
    if not timetable_can_be_managed(timetable) or (db.session.get(User, session["user_id"]).role == "faculty" and timetable.status != "Draft"):
        return "Timetable management authorization required.", 403
    entry = TimetableEntry.query.filter_by(id=entry_id, timetable_id=timetable.id).first_or_404()
    db.session.delete(entry)
    db.session.commit()
    return redirect(url_for("manage_timetable_detail", timetable_id=timetable.id))


def parse_activity_form(form):
    title = form.get("title", "").strip()
    description = form.get("description", "").strip()
    activity_category = form.get("activity_category", "").strip()
    activity_type = form.get("activity_type", "").strip()
    activity_date = form.get("activity_date", "").strip()
    organizer = form.get("organizer", "").strip() or None
    location = form.get("location", "").strip() or None
    submitted_status = form.get("verification_status")

    try:
        parsed_date = datetime.strptime(activity_date, "%Y-%m-%d").date()
    except ValueError:
        parsed_date = None

    errors = []
    if not title:
        errors.append("Title is required.")
    if not description:
        errors.append("Description is required.")
    if len(title) > 120 or len(description) > 1000:
        errors.append("Title or description is too long.")
    if len(organizer or "") > 120 or len(location or "") > 120:
        errors.append("Organizer or location is too long.")
    if parsed_date is None:
        errors.append("Enter a valid activity date.")
    if activity_category not in app.config["ACTIVITY_CATEGORIES"]:
        errors.append("Choose a valid activity category.")
    if activity_type not in app.config["ACTIVITY_TYPES"]:
        errors.append("Choose a valid activity type.")
    if submitted_status is not None and submitted_status != "Pending":
        errors.append("Verification status can only be assigned by a future review workflow.")

    return {
        "title": title,
        "description": description,
        "activity_category": activity_category,
        "activity_type": activity_type,
        "activity_date": parsed_date,
        "organizer": organizer,
        "location": location,
    }, errors


def activity_form_context(activity=None, form_data=None, form_error=None):
    return {
        "activity": activity,
        "subjects": Subject.query.filter_by(user_id=session["user_id"]).order_by(Subject.name).all(),
        "categories": sorted(app.config["ACTIVITY_CATEGORIES"]),
        "activity_types": sorted(app.config["ACTIVITY_TYPES"]),
        "form_data": form_data or {},
        "form_error": form_error,
        "today": date.today().isoformat(),
    }


@app.route("/activities")
@login_required
def activities():
    user_id = session["user_id"]
    query = AcademicActivity.query.filter_by(user_id=user_id)
    subject_id = request.args.get("subject_id", type=int)
    category = request.args.get("category", "").strip()
    activity_type = request.args.get("activity_type", "").strip()

    if subject_id is not None:
        query = query.filter_by(subject_id=subject_id)
    if category in app.config["ACTIVITY_CATEGORIES"]:
        query = query.filter_by(activity_category=category)
    if activity_type in app.config["ACTIVITY_TYPES"]:
        query = query.filter_by(activity_type=activity_type)

    activity_records = query.order_by(
        AcademicActivity.activity_date.desc(), AcademicActivity.id.desc()
    ).all()
    return render_template(
        "activities.html",
        activities=activity_records,
        subjects=Subject.query.filter_by(user_id=user_id).order_by(Subject.name).all(),
        categories=sorted(app.config["ACTIVITY_CATEGORIES"]),
        activity_types=sorted(app.config["ACTIVITY_TYPES"]),
        selected_subject_id=subject_id,
        selected_category=category,
        selected_activity_type=activity_type,
    )


@app.route("/activities/add", methods=["GET", "POST"])
@login_required
def add_activity():
    if request.method == "GET":
        return render_template("activity_form.html", **activity_form_context())

    values, errors = parse_activity_form(request.form)
    subject_id = request.form.get("subject_id", type=int)
    subject = Subject.query.filter_by(id=subject_id, user_id=session["user_id"]).first() if subject_id else None
    if subject_id and subject is None:
        errors.append("Choose one of your subjects.")
    if errors:
        return render_template(
            "activity_form.html",
            **activity_form_context(form_data=request.form, form_error=" ".join(errors)),
        )

    activity = AcademicActivity(
        **values,
        user_id=session["user_id"],
        subject_id=subject.id if subject else None,
        verification_status="Pending",
    )
    db.session.add(activity)
    db.session.commit()
    flash("Activity added successfully.", "success")
    return redirect(url_for("activity_detail", activity_id=activity.id))


@app.route("/activities/<int:activity_id>")
@login_required
def activity_detail(activity_id):
    activity = AcademicActivity.query.filter_by(
        id=activity_id, user_id=session["user_id"]
    ).first_or_404()
    return render_template("activity_detail.html", activity=activity)


@app.route("/activities/<int:activity_id>/edit", methods=["GET", "POST"])
@login_required
def edit_activity(activity_id):
    activity = AcademicActivity.query.filter_by(
        id=activity_id, user_id=session["user_id"]
    ).first_or_404()
    if request.method == "GET":
        return render_template("activity_form.html", **activity_form_context(activity=activity))

    values, errors = parse_activity_form(request.form)
    subject_id = request.form.get("subject_id", type=int)
    subject = Subject.query.filter_by(id=subject_id, user_id=session["user_id"]).first() if subject_id else None
    if subject_id and subject is None:
        errors.append("Choose one of your subjects.")
    if errors:
        return render_template(
            "activity_form.html",
            **activity_form_context(activity=activity, form_data=request.form, form_error=" ".join(errors)),
        )

    for field, value in values.items():
        setattr(activity, field, value)
    activity.subject_id = subject.id if subject else None
    db.session.commit()
    flash("Activity updated successfully.", "success")
    return redirect(url_for("activity_detail", activity_id=activity.id))


@app.route("/activities/<int:activity_id>/delete", methods=["POST"])
@login_required
def delete_activity(activity_id):
    activity = AcademicActivity.query.filter_by(
        id=activity_id, user_id=session["user_id"]
    ).first_or_404()
    db.session.delete(activity)
    db.session.commit()
    flash("Activity deleted successfully.", "success")
    return redirect(url_for("activities"))


def get_owned_parent(parent_type, parent_id):
    parent_models = {
        "activity": AcademicActivity,
        "assessment": Assessment,
        "attendance": Attendance,
    }
    parent_model = parent_models[parent_type]
    return parent_model.query.filter_by(id=parent_id, user_id=session["user_id"]).first_or_404()


def parent_evidence_filter(parent_type, parent_id):
    parent_columns = {
        "activity": EvidenceAttachment.activity_id,
        "assessment": EvidenceAttachment.assessment_id,
        "attendance": EvidenceAttachment.attendance_id,
    }
    return parent_columns[parent_type] == parent_id


def evidence_form_context(parent_type, parent, form_error=None):
    return {
        "parent_type": parent_type,
        "parent": parent,
        "form_error": form_error,
        "max_size_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
    }


def validate_evidence_file(upload):
    if upload is None or not upload.filename:
        return None, "Please choose a PDF, PNG, JPG, or JPEG file."

    original_filename = upload.filename.replace("\\", "/").rsplit("/", 1)[-1]
    extension = os.path.splitext(original_filename.lower())[1]
    file_rule = app.config["EVIDENCE_MIME_TYPES"].get(extension)
    if file_rule is None:
        return None, "Unsupported file type. Use PDF, PNG, JPG, or JPEG."

    content = upload.stream.read(app.config["MAX_CONTENT_LENGTH"] + 1)
    upload.stream.seek(0)
    if len(content) > app.config["MAX_CONTENT_LENGTH"]:
        return None, "The evidence file is too large. The maximum size is 5 MB."

    expected_mime, signature = file_rule
    if upload.mimetype.lower() != expected_mime or not content.startswith(signature):
        return None, "The file type and file content do not match."

    return {
        "original_filename": original_filename,
        "extension": extension,
        "mime_type": expected_mime,
        "file_size": len(content),
    }, None


def evidence_path(evidence):
    upload_dir = os.path.abspath(app.config["EVIDENCE_UPLOAD_DIR"])
    candidate = os.path.abspath(os.path.join(upload_dir, evidence.stored_filename))
    if os.path.commonpath([upload_dir, candidate]) != upload_dir:
        return None
    return candidate


def render_evidence_form(parent_type, parent, form_error=None):
    return render_template(
        "evidence_form.html",
        **evidence_form_context(parent_type, parent, form_error),
    )


def add_evidence_for_parent(parent_type, parent_id):
    parent = get_owned_parent(parent_type, parent_id)
    if request.method == "GET":
        return render_evidence_form(parent_type, parent)

    file_info, error = validate_evidence_file(request.files.get("evidence_file"))
    description = request.form.get("description", "").strip() or None
    if len(description or "") > 255:
        error = "The description must be 255 characters or fewer."
    if error:
        return render_evidence_form(parent_type, parent, error)

    stored_filename = f"{uuid.uuid4().hex}{file_info['extension']}"
    storage_path = os.path.abspath(os.path.join(app.config["EVIDENCE_UPLOAD_DIR"], stored_filename))
    if os.path.commonpath([os.path.abspath(app.config["EVIDENCE_UPLOAD_DIR"]), storage_path]) != os.path.abspath(app.config["EVIDENCE_UPLOAD_DIR"]):
        return render_evidence_form(parent_type, parent, "Unable to create a safe storage path.")

    upload = request.files["evidence_file"]
    try:
        upload.save(storage_path)
        parent_ids = {"activity_id": None, "assessment_id": None, "attendance_id": None}
        parent_ids[f"{parent_type}_id"] = parent.id
        evidence = EvidenceAttachment(
            **parent_ids,
            user_id=session["user_id"],
            original_filename=file_info["original_filename"],
            stored_filename=stored_filename,
            storage_path=storage_path,
            mime_type=file_info["mime_type"],
            file_size=file_info["file_size"],
            description=description,
            verification_status="Pending",
        )
        db.session.add(evidence)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if os.path.isfile(storage_path):
            os.remove(storage_path)
        raise

    flash("Evidence attached successfully.", "success")
    if parent_type == "activity":
        return redirect(url_for("activity_detail", activity_id=parent.id))
    if parent_type == "assessment":
        return redirect(url_for("assessments"))
    return redirect(url_for("attendance", subject_id=parent.subject_id))


def get_owned_evidence(parent_type, parent_id, evidence_id):
    get_owned_parent(parent_type, parent_id)
    return EvidenceAttachment.query.filter(
        EvidenceAttachment.id == evidence_id,
        EvidenceAttachment.user_id == session["user_id"],
        parent_evidence_filter(parent_type, parent_id),
    ).first_or_404()


def evidence_detail_for_parent(parent_type, parent_id, evidence_id):
    parent = get_owned_parent(parent_type, parent_id)
    evidence = get_owned_evidence(parent_type, parent_id, evidence_id)
    return render_template("evidence_detail.html", parent_type=parent_type, parent=parent, evidence=evidence)


def download_evidence_for_parent(parent_type, parent_id, evidence_id):
    evidence = get_owned_evidence(parent_type, parent_id, evidence_id)
    path = evidence_path(evidence)
    if path is None or not os.path.isfile(path):
        return "Evidence file not found.", 404
    return send_file(path, mimetype=evidence.mime_type, as_attachment=False, download_name=evidence.original_filename)


def delete_evidence_for_parent(parent_type, parent_id, evidence_id):
    evidence = get_owned_evidence(parent_type, parent_id, evidence_id)
    path = evidence_path(evidence)
    db.session.delete(evidence)
    db.session.commit()
    if path is not None and os.path.isfile(path):
        try:
            os.remove(path)
        except PermissionError:
            flash("Evidence was removed from the database but its file is still in use.", "warning")
    flash("Evidence deleted successfully.", "success")
    if parent_type == "activity":
        return redirect(url_for("activity_detail", activity_id=parent_id))
    if parent_type == "assessment":
        return redirect(url_for("assessments"))
    return redirect(url_for("attendance"))


@app.errorhandler(RequestEntityTooLarge)
def handle_oversized_evidence(error):
    return "The evidence file is too large. The maximum size is 5 MB.", 413


@app.route("/activities/<int:activity_id>/evidence/add", methods=["GET", "POST"])
@login_required
def add_activity_evidence(activity_id):
    return add_evidence_for_parent("activity", activity_id)


@app.route("/activities/<int:activity_id>/evidence/<int:evidence_id>")
@login_required
def activity_evidence_detail(activity_id, evidence_id):
    return evidence_detail_for_parent("activity", activity_id, evidence_id)


@app.route("/activities/<int:activity_id>/evidence/<int:evidence_id>/download")
@login_required
def download_activity_evidence(activity_id, evidence_id):
    return download_evidence_for_parent("activity", activity_id, evidence_id)


@app.route("/activities/<int:activity_id>/evidence/<int:evidence_id>/delete", methods=["POST"])
@login_required
def delete_activity_evidence(activity_id, evidence_id):
    return delete_evidence_for_parent("activity", activity_id, evidence_id)


@app.route("/assessments/<int:assessment_id>/evidence/add", methods=["GET", "POST"])
@login_required
def add_assessment_evidence(assessment_id):
    return add_evidence_for_parent("assessment", assessment_id)


@app.route("/assessments/<int:assessment_id>/evidence/<int:evidence_id>")
@login_required
def assessment_evidence_detail(assessment_id, evidence_id):
    return evidence_detail_for_parent("assessment", assessment_id, evidence_id)


@app.route("/assessments/<int:assessment_id>/evidence/<int:evidence_id>/download")
@login_required
def download_assessment_evidence(assessment_id, evidence_id):
    return download_evidence_for_parent("assessment", assessment_id, evidence_id)


@app.route("/assessments/<int:assessment_id>/evidence/<int:evidence_id>/delete", methods=["POST"])
@login_required
def delete_assessment_evidence(assessment_id, evidence_id):
    return delete_evidence_for_parent("assessment", assessment_id, evidence_id)


@app.route("/attendance/<int:attendance_id>/evidence/add", methods=["GET", "POST"])
@login_required
def add_attendance_evidence(attendance_id):
    return add_evidence_for_parent("attendance", attendance_id)


@app.route("/attendance/<int:attendance_id>/evidence/<int:evidence_id>")
@login_required
def attendance_evidence_detail(attendance_id, evidence_id):
    return evidence_detail_for_parent("attendance", attendance_id, evidence_id)


@app.route("/attendance/<int:attendance_id>/evidence/<int:evidence_id>/download")
@login_required
def download_attendance_evidence(attendance_id, evidence_id):
    return download_evidence_for_parent("attendance", attendance_id, evidence_id)


@app.route("/attendance/<int:attendance_id>/evidence/<int:evidence_id>/delete", methods=["POST"])
@login_required
def delete_attendance_evidence(attendance_id, evidence_id):
    return delete_evidence_for_parent("attendance", attendance_id, evidence_id)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = db.get_or_404(User, session["user_id"])
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        student_id = request.form.get("student_id", "").strip()

        if not full_name or not student_id:
            flash("Full name and student ID are required.", "danger")
            return render_template("profile.html", user=user)

        duplicate = User.query.filter(
            User.student_id == student_id, User.id != user.id
        ).first()
        if duplicate:
            flash("That student ID is already in use.", "danger")
            return render_template("profile.html", user=user)

        user.full_name = full_name
        user.student_id = student_id
        user.branch = request.form.get("branch", "").strip() or None
        user.semester = request.form.get("semester", "").strip() or None
        user.section = request.form.get("section", "").strip() or None
        user.academic_year = request.form.get("academic_year", "").strip() or None
        user.batch_group = request.form.get("batch_group", "").strip() or None
        user.academic_year = request.form.get("academic_year", "").strip() or None
        user.batch_group = request.form.get("batch_group", "").strip() or None
        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("profile"))

    return render_template("profile.html", user=user)


@app.route("/subjects")
@login_required
def subjects():
    student_subjects = Subject.query.filter_by(user_id=session["user_id"]).order_by(Subject.name).all()
    return render_template("subjects.html", subjects=student_subjects)


@app.route("/subjects/add", methods=["GET", "POST"])
@login_required
def add_subject():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        faculty_name = request.form.get("faculty_name", "").strip() or None
        credits_value = request.form.get("credits", "").strip()

        if not name or not code:
            flash("Subject name and subject code are required.", "danger")
            return render_template("subject_form.html", subject=None)

        credits = None
        if credits_value:
            try:
                credits = int(credits_value)
                if credits < 0:
                    raise ValueError
            except ValueError:
                flash("Credits must be a non-negative whole number.", "danger")
                return render_template("subject_form.html", subject=None)

        subject = Subject(
            name=name,
            code=code,
            faculty_name=faculty_name,
            credits=credits,
            user_id=session["user_id"],
        )
        db.session.add(subject)
        db.session.commit()
        flash("Subject added successfully.", "success")
        return redirect(url_for("subjects"))

    return render_template("subject_form.html", subject=None)


@app.route("/subjects/<int:subject_id>/edit", methods=["GET", "POST"])
@login_required
def edit_subject(subject_id):
    subject = Subject.query.filter_by(id=subject_id, user_id=session["user_id"]).first_or_404()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip()
        faculty_name = request.form.get("faculty_name", "").strip() or None
        credits_value = request.form.get("credits", "").strip()

        if not name or not code:
            flash("Subject name and subject code are required.", "danger")
            return render_template("subject_form.html", subject=subject)

        credits = None
        if credits_value:
            try:
                credits = int(credits_value)
                if credits < 0:
                    raise ValueError
            except ValueError:
                flash("Credits must be a non-negative whole number.", "danger")
                return render_template("subject_form.html", subject=subject)

        subject.name = name
        subject.code = code
        subject.faculty_name = faculty_name
        subject.credits = credits
        db.session.commit()
        flash("Subject updated successfully.", "success")
        return redirect(url_for("subjects"))

    return render_template("subject_form.html", subject=subject)


@app.route("/subjects/<int:subject_id>/delete", methods=["POST"])
@login_required
def delete_subject(subject_id):
    subject = Subject.query.filter_by(id=subject_id, user_id=session["user_id"]).first_or_404()
    db.session.delete(subject)
    db.session.commit()
    flash("Subject deleted successfully.", "success")
    return redirect(url_for("subjects"))


def attendance_summary(records):
    factual_records = [record for record in records if record.status in {"Present", "Absent"}]
    total = len(factual_records)
    attended = sum(record.status == "Present" for record in factual_records)
    missed = sum(record.status == "Absent" for record in factual_records)
    percentage = round((attended / total) * 100, 2) if total else None
    return {"total": total, "attended": attended, "missed": missed, "percentage": percentage}


def get_attendance_form_values():
    record_date = request.form.get("record_date", "").strip()
    status = request.form.get("status", "").strip()
    class_type = request.form.get("class_type", "").strip() or None
    topic = request.form.get("topic", "").strip() or None

    try:
        parsed_date = datetime.strptime(record_date, "%Y-%m-%d").date()
    except ValueError:
        parsed_date = None

    if parsed_date is None or status not in {"Present", "Absent"}:
        return None
    if class_type not in {None, "Lecture", "Lab"}:
        return None
    return parsed_date, status, class_type, topic


def render_attendance_page(selected_subject_id=None, form_error=None):
    user_id = session["user_id"]
    student_subjects = Subject.query.filter_by(user_id=user_id).order_by(Subject.name).all()
    selected_subject = None
    if selected_subject_id is not None:
        selected_subject = next(
            (subject for subject in student_subjects if subject.id == selected_subject_id), None
        )

    records = []
    summary = {"total": 0, "attended": 0, "missed": 0, "percentage": None}
    if selected_subject is not None:
        records = Attendance.query.filter_by(
            user_id=user_id, subject_id=selected_subject.id
        ).order_by(Attendance.record_date.desc(), Attendance.id.desc()).all()
        summary = attendance_summary(records)

    summaries = []
    for subject in student_subjects:
        subject_records = Attendance.query.filter_by(
            user_id=user_id, subject_id=subject.id
        ).all()
        summaries.append({"subject": subject, "summary": attendance_summary(subject_records)})

    all_records = Attendance.query.filter_by(user_id=user_id).all()
    overall = attendance_summary(all_records)
    return render_template(
        "attendance.html",
        subjects=student_subjects,
        selected_subject=selected_subject,
        records=records,
        summary=summary,
        summaries=summaries,
        overall=overall,
        form_error=form_error,
        today=date.today().isoformat(),
    )


@app.route("/attendance")
@login_required
def attendance():
    selected_subject_id = request.args.get("subject_id", type=int)
    return render_attendance_page(selected_subject_id)


@app.route("/attendance/add", methods=["POST"])
@login_required
def add_attendance():
    subject_id = request.form.get("subject_id", type=int)
    subject = Subject.query.filter_by(id=subject_id, user_id=session["user_id"]).first()
    values = get_attendance_form_values()
    if subject is None:
        return render_attendance_page(form_error="Please select one of your subjects.")
    if values is None:
        return render_attendance_page(
            selected_subject_id=subject.id,
            form_error="Enter a valid date, status, and class type.",
        )

    record_date, status, class_type, topic = values
    record = Attendance(
        record_date=record_date,
        status=status,
        class_type=class_type,
        topic=topic,
        classes_held=1,
        classes_attended=1 if status == "Present" else 0,
        user_id=session["user_id"],
        subject_id=subject.id,
    )
    db.session.add(record)
    db.session.commit()
    flash("Attendance record added.", "success")
    return redirect(url_for("attendance", subject_id=subject.id))


@app.route("/attendance/<int:attendance_id>/edit", methods=["GET", "POST"])
@login_required
def edit_attendance(attendance_id):
    record = Attendance.query.filter_by(
        id=attendance_id, user_id=session["user_id"]
    ).first_or_404()
    if request.method == "POST":
        values = get_attendance_form_values()
        if values is None:
            return render_template("attendance_form.html", record=record, form_error="Enter a valid date, status, and class type.")
        record.record_date, record.status, record.class_type, record.topic = values
        record.classes_attended = 1 if record.status == "Present" else 0
        db.session.commit()
        flash("Attendance record updated.", "success")
        return redirect(url_for("attendance", subject_id=record.subject_id))
    return render_template("attendance_form.html", record=record, form_error=None)


@app.route("/attendance/<int:attendance_id>/delete", methods=["POST"])
@login_required
def delete_attendance(attendance_id):
    record = Attendance.query.filter_by(
        id=attendance_id, user_id=session["user_id"]
    ).first_or_404()
    subject_id = record.subject_id
    db.session.delete(record)
    db.session.commit()
    flash("Attendance record deleted.", "success")
    return redirect(url_for("attendance", subject_id=subject_id))


def assessment_summary(records):
    marks_obtained = sum((Decimal(str(record.marks_obtained)) for record in records), Decimal("0"))
    maximum_marks = sum((Decimal(str(record.maximum_marks)) for record in records), Decimal("0"))
    percentage = round((marks_obtained / maximum_marks) * 100, 2) if maximum_marks else None
    return {
        "count": len(records),
        "marks_obtained": marks_obtained,
        "maximum_marks": maximum_marks,
        "percentage": percentage,
    }


def get_assessment_form_values():
    assessment_type = request.form.get("assessment_type", "").strip()
    assessment_title = request.form.get("assessment_title", "").strip()
    remarks = request.form.get("remarks", "").strip() or None
    assessment_date = request.form.get("assessment_date", "").strip()
    marks_obtained_value = request.form.get("marks_obtained", "").strip()
    maximum_marks_value = request.form.get("maximum_marks", "").strip()

    try:
        parsed_date = datetime.strptime(assessment_date, "%Y-%m-%d").date()
        marks_obtained = Decimal(marks_obtained_value)
        maximum_marks = Decimal(maximum_marks_value)
    except (ValueError, InvalidOperation):
        return None

    if not assessment_type or not assessment_title:
        return None
    if not marks_obtained.is_finite() or not maximum_marks.is_finite():
        return None
    if marks_obtained < 0 or maximum_marks <= 0 or marks_obtained > maximum_marks:
        return None
    return parsed_date, assessment_type, assessment_title, marks_obtained, maximum_marks, remarks


def render_assessment_page(selected_subject_id=None, form_error=None):
    user_id = session["user_id"]
    student_subjects = Subject.query.filter_by(user_id=user_id).order_by(Subject.name).all()
    selected_subject = next(
        (subject for subject in student_subjects if subject.id == selected_subject_id), None
    ) if selected_subject_id is not None else None
    query = Assessment.query.filter_by(user_id=user_id)
    if selected_subject is not None:
        query = query.filter_by(subject_id=selected_subject.id)
    records = query.order_by(Assessment.assessment_date.desc(), Assessment.id.desc()).all()

    summaries = []
    for subject in student_subjects:
        subject_records = Assessment.query.filter_by(
            user_id=user_id, subject_id=subject.id
        ).all()
        summaries.append({"subject": subject, "summary": assessment_summary(subject_records)})
    overall = assessment_summary(Assessment.query.filter_by(user_id=user_id).all())
    return render_template(
        "assessments.html",
        subjects=student_subjects,
        selected_subject=selected_subject,
        records=records,
        summaries=summaries,
        overall=overall,
        form_error=form_error,
        today=date.today().isoformat(),
    )


@app.route("/assessments")
@login_required
def assessments():
    selected_subject_id = request.args.get("subject_id", type=int)
    return render_assessment_page(selected_subject_id)


@app.route("/assessments/add", methods=["GET", "POST"])
@login_required
def add_assessment():
    if request.method == "GET":
        return render_template(
            "assessment_form.html",
            subjects=Subject.query.filter_by(user_id=session["user_id"]).order_by(Subject.name).all(),
            record=None,
            form_error=None,
            today=date.today().isoformat(),
        )

    subject_id = request.form.get("subject_id", type=int)
    subject = Subject.query.filter_by(id=subject_id, user_id=session["user_id"]).first()
    values = get_assessment_form_values()
    if subject is None:
        return render_assessment_page(form_error="Please select one of your subjects.")
    if values is None:
        return render_assessment_page(
            selected_subject_id=subject.id,
            form_error="Enter valid assessment details and marks within the maximum.",
        )

    assessment_date, assessment_type, title, marks_obtained, maximum_marks, remarks = values
    record = Assessment(
        assessment_type=assessment_type,
        assessment_title=title,
        marks_obtained=float(marks_obtained),
        maximum_marks=float(maximum_marks),
        assessment_date=assessment_date,
        remarks=remarks,
        user_id=session["user_id"],
        subject_id=subject.id,
    )
    db.session.add(record)
    db.session.commit()
    flash("Assessment added successfully.", "success")
    return redirect(url_for("assessments", subject_id=subject.id))


@app.route("/assessments/<int:assessment_id>/edit", methods=["GET", "POST"])
@login_required
def edit_assessment(assessment_id):
    record = Assessment.query.filter_by(
        id=assessment_id, user_id=session["user_id"]
    ).first_or_404()
    subjects_for_user = Subject.query.filter_by(user_id=session["user_id"]).order_by(Subject.name).all()
    if request.method == "POST":
        subject_id = request.form.get("subject_id", type=int)
        subject = Subject.query.filter_by(id=subject_id, user_id=session["user_id"]).first()
        values = get_assessment_form_values()
        if subject is None or values is None:
            return render_template(
                "assessment_form.html",
                subjects=subjects_for_user,
                record=record,
                form_error="Choose one of your subjects and enter valid marks within the maximum.",
                today=date.today().isoformat(),
            )
        assessment_date, assessment_type, title, marks_obtained, maximum_marks, remarks = values
        record.subject_id = subject.id
        record.assessment_type = assessment_type
        record.assessment_title = title
        record.marks_obtained = float(marks_obtained)
        record.maximum_marks = float(maximum_marks)
        record.assessment_date = assessment_date
        record.remarks = remarks
        db.session.commit()
        flash("Assessment updated successfully.", "success")
        return redirect(url_for("assessments", subject_id=subject.id))
    return render_template(
        "assessment_form.html",
        subjects=subjects_for_user,
        record=record,
        form_error=None,
        today=date.today().isoformat(),
    )


@app.route("/assessments/<int:assessment_id>/delete", methods=["POST"])
@login_required
def delete_assessment(assessment_id):
    record = Assessment.query.filter_by(
        id=assessment_id, user_id=session["user_id"]
    ).first_or_404()
    subject_id = record.subject_id
    db.session.delete(record)
    db.session.commit()
    flash("Assessment deleted successfully.", "success")
    return redirect(url_for("assessments", subject_id=subject_id))


def parse_review_form(assessment, form):
    reviewed_value = form.get("reviewed_marks_obtained", "").strip()
    review_note = form.get("review_note", "").strip() or None
    errors = []

    try:
        reviewed_marks = Decimal(reviewed_value)
    except InvalidOperation:
        reviewed_marks = None

    maximum_marks = Decimal(str(assessment.maximum_marks))
    if maximum_marks <= 0:
        errors.append("The assessment maximum marks must be greater than zero.")
    if reviewed_marks is None or not reviewed_marks.is_finite():
        errors.append("Reviewed marks must be numeric.")
    elif reviewed_marks < 0 or reviewed_marks > maximum_marks:
        errors.append("Reviewed marks must be between zero and the maximum marks.")
    if len(review_note or "") > 1000:
        errors.append("The review note must be 1000 characters or fewer.")

    if errors:
        return None, errors

    recorded_marks = Decimal(str(assessment.marks_obtained))
    difference = reviewed_marks - recorded_marks
    if difference != 0 and not review_note:
        errors.append("A review note is required when a difference is found.")
        return None, errors

    status = "No Difference" if difference == 0 else "Difference Found"
    return {
        "reviewed_marks_obtained": reviewed_marks,
        "recorded_marks_obtained": recorded_marks,
        "difference": difference,
        "review_note": review_note,
        "review_status": status,
    }, []


def review_form_context(assessment, review=None, form_error=None):
    return {
        "assessment": assessment,
        "review": review,
        "form_error": form_error,
    }


@app.route("/assessments/<int:assessment_id>/review", methods=["GET", "POST"])
@login_required
def create_assessment_review(assessment_id):
    assessment = Assessment.query.filter_by(
        id=assessment_id, user_id=session["user_id"]
    ).first_or_404()
    if request.method == "GET":
        return render_template("review_form.html", **review_form_context(assessment))

    values, errors = parse_review_form(assessment, request.form)
    if errors:
        return render_template(
            "review_form.html",
            **review_form_context(assessment, form_error=" ".join(errors)),
        )

    review = AcademicReview(
        user_id=session["user_id"],
        assessment_id=assessment.id,
        recorded_marks_obtained=float(values["recorded_marks_obtained"]),
        reviewed_marks_obtained=float(values["reviewed_marks_obtained"]),
        difference=float(values["difference"]),
        review_note=values["review_note"],
        review_status=values["review_status"],
    )
    db.session.add(review)
    db.session.commit()
    flash("Assessment review recorded.", "success")
    return redirect(url_for("review_detail", review_id=review.id))


@app.route("/reviews")
@login_required
def reviews():
    review_records = AcademicReview.query.filter_by(
        user_id=session["user_id"]
    ).order_by(AcademicReview.created_at.desc(), AcademicReview.id.desc()).all()
    return render_template("reviews.html", reviews=review_records)


@app.route("/reviews/<int:review_id>")
@login_required
def review_detail(review_id):
    review = AcademicReview.query.filter_by(
        id=review_id, user_id=session["user_id"]
    ).first_or_404()
    evidence = EvidenceAttachment.query.filter_by(
        assessment_id=review.assessment_id, user_id=session["user_id"]
    ).order_by(EvidenceAttachment.uploaded_at.desc()).all()
    return render_template("review_detail.html", review=review, evidence=evidence)


@app.route("/reviews/<int:review_id>/edit", methods=["GET", "POST"])
@login_required
def edit_review(review_id):
    review = AcademicReview.query.filter_by(
        id=review_id, user_id=session["user_id"]
    ).first_or_404()
    assessment = Assessment.query.filter_by(
        id=review.assessment_id, user_id=session["user_id"]
    ).first_or_404()
    if request.method == "GET":
        return render_template("review_form.html", **review_form_context(assessment, review))

    values, errors = parse_review_form(assessment, request.form)
    if errors:
        return render_template(
            "review_form.html",
            **review_form_context(assessment, review, " ".join(errors)),
        )

    review.reviewed_marks_obtained = float(values["reviewed_marks_obtained"])
    review.difference = float(values["difference"])
    review.review_note = values["review_note"]
    review.review_status = values["review_status"]
    db.session.commit()
    flash("Assessment review updated.", "success")
    return redirect(url_for("review_detail", review_id=review.id))


@app.route("/reviews/<int:review_id>/delete", methods=["POST"])
@login_required
def delete_review(review_id):
    review = AcademicReview.query.filter_by(
        id=review_id, user_id=session["user_id"]
    ).first_or_404()
    db.session.delete(review)
    db.session.commit()
    flash("Assessment review deleted.", "success")
    return redirect(url_for("reviews"))


if __name__ == "__main__":
    app.run(debug=True)