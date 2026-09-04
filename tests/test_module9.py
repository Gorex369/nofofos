from io import BytesIO

from app import app, db
from models import OfficialTimetable, TimetableEntry, User


STUDENT_EMAIL = "module9.student@example.com"
COORDINATOR_EMAIL = "module9.coordinator@example.com"
OTHER_STUDENT_EMAIL = "module9.other@example.com"


def pdf_upload(filename="official.pdf", content=b"%PDF-1.7 timetable"):
    return {"timetable_file": (BytesIO(content), filename, "application/pdf")}


def register(client, email, student_id):
    return client.post("/register", data={
        "full_name": "Module 9 Test",
        "student_id": student_id,
        "email": email,
        "password": "testpass123",
    })


def timetable_form():
    return {
        "academic_year": "2026-27",
        "semester": "5",
        "programme": "CSE",
        "section": "A",
        "batch_group": "G1",
        "effective_from": "2026-01-01",
        "effective_until": "2027-12-31",
    }


def test_official_timetable_versioning_matching_and_security():
    app.config.update(TESTING=True)
    created_user_ids = []
    created_timetable_ids = []

    with app.app_context():
        assert not User.query.filter(User.email.in_((STUDENT_EMAIL, COORDINATOR_EMAIL, OTHER_STUDENT_EMAIL))).first(), (
            "A Module 9 test account already exists; refusing to delete it."
        )

    client = app.test_client()
    assert client.get("/timetable").status_code == 302
    assert client.get("/coordinator/timetables").status_code == 302

    try:
        for email, student_id in ((STUDENT_EMAIL, "M9-STUDENT"), (COORDINATOR_EMAIL, "M9-COORD"), (OTHER_STUDENT_EMAIL, "M9-OTHER")):
            assert register(client, email, student_id).status_code == 302
            with app.app_context():
                created_user_ids.append(User.query.filter_by(email=email).first().id)

        with app.app_context():
            coordinator = db.session.get(User, created_user_ids[1])
            coordinator.role = "coordinator"
            student = db.session.get(User, created_user_ids[0])
            student.branch = "CSE"
            student.semester = "5"
            student.section = "A"
            student.academic_year = "2026-27"
            student.batch_group = "G1"
            other_student = db.session.get(User, created_user_ids[2])
            other_student.branch = "ECE"
            other_student.semester = "5"
            other_student.section = "A"
            other_student.academic_year = "2026-27"
            db.session.commit()

        client.post("/logout")
        client.post("/login", data={"email": STUDENT_EMAIL, "password": "testpass123"})
        assert client.get("/timetable").status_code == 200
        assert b"No official timetable is currently available" in client.get("/timetable").data
        assert client.get("/coordinator/timetables").status_code == 403

        client.post("/logout")
        client.post("/login", data={"email": COORDINATOR_EMAIL, "password": "testpass123"})
        response = client.post("/coordinator/timetables/add", data=timetable_form() | pdf_upload(), content_type="multipart/form-data")
        assert response.status_code == 302
        with app.test_request_context():
            pass
        with app.app_context():
            timetable = OfficialTimetable.query.first()
            assert timetable.version_number == 1 and timetable.status == "Draft"
            assert timetable.original_filename == "official.pdf"
            assert timetable.stored_filename != timetable.original_filename
            assert timetable.stored_filename.endswith(".pdf")
            timetable_id = timetable.id
            created_timetable_ids.append(timetable_id)

        assert client.post(f"/coordinator/timetables/{timetable_id}/entries/add", data={
            "day_of_week": "Monday", "start_time": "09:00", "end_time": "10:00", "subject_name": "Data Structures", "room_lab": "Lab 1", "faculty_name": "Dr. Test", "batch_group": "G1"
        }).status_code == 302
        assert client.post(f"/coordinator/timetables/{timetable_id}/publish").status_code == 302
        with app.app_context():
            timetable = db.session.get(OfficialTimetable, timetable_id)
            assert timetable.status == "Published"
            entry = TimetableEntry.query.filter_by(timetable_id=timetable_id).first()
            assert entry is not None
            entry_id = entry.id

        invalid_day = client.post(f"/coordinator/timetables/{timetable_id}/entries/add", data={"day_of_week": "Funday", "start_time": "10:00", "end_time": "09:00", "subject_name": "Bad Entry"})
        assert invalid_day.status_code == 200
        assert b"valid day" in invalid_day.data and b"after start time" in invalid_day.data
        assert client.post(f"/coordinator/timetables/{timetable_id}/entries/{entry_id}/delete").status_code == 302
        assert client.post(f"/coordinator/timetables/{timetable_id}/entries/add", data={"day_of_week": "Monday", "start_time": "09:00", "end_time": "10:00", "subject_name": "Data Structures", "batch_group": "G1"}).status_code == 302

        version_two = client.post("/coordinator/timetables/add", data=timetable_form() | {"effective_from": "2026-06-01"} | pdf_upload("revised.pdf"), content_type="multipart/form-data")
        assert version_two.status_code == 302
        with app.app_context():
            second = OfficialTimetable.query.filter_by(original_filename="revised.pdf").first()
            assert second.version_number == 2 and second.status == "Draft"
            second_id = second.id
            created_timetable_ids.append(second_id)
        assert client.post(f"/coordinator/timetables/{second_id}/publish").status_code == 302
        with app.app_context():
            first = db.session.get(OfficialTimetable, timetable_id)
            second = db.session.get(OfficialTimetable, second_id)
            assert first.status == "Archived" and second.status == "Published"

        client.post("/logout")
        client.post("/login", data={"email": STUDENT_EMAIL, "password": "testpass123"})
        student_timetable = client.get("/timetable")
        assert student_timetable.status_code == 200
        assert b"revised.pdf" not in student_timetable.data
        assert b"Version" in student_timetable.data
        assert client.get("/timetable/document").status_code == 200
        assert client.get("/timetable/document").data.startswith(b"%PDF")

        client.post("/logout")
        client.post("/login", data={"email": OTHER_STUDENT_EMAIL, "password": "testpass123"})
        assert b"No official timetable is currently available" in client.get("/timetable").data
        assert client.get("/coordinator/timetables").status_code == 403
    finally:
        with app.app_context():
            for timetable_id in created_timetable_ids:
                timetable = db.session.get(OfficialTimetable, timetable_id)
                if timetable is not None:
                    db.session.delete(timetable)
            for user_id in created_user_ids:
                user = db.session.get(User, user_id)
                if user is not None:
                    db.session.delete(user)
            db.session.commit()
