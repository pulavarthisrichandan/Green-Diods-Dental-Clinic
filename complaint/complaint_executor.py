"""
complaint/complaint_executor.py  --  DentalBot v2
Two-path complaint saving:
  TYPE 1 (general)   : first_name, last_name, contact_number, complaint_text
  TYPE 2 (treatment) : verified patient -- saves patient_id, appointment_id,
                       DOB, contact, treatment_name, dentist_name, date/time
"""

from db.db_connection import db_cursor
from utils.text_utils import title_case
from utils.phone_utils import normalize_phone, format_phone_for_speech
import traceback


def save_complaint(
    complaint_category: str,
    complaint_text: str,
    # ── TYPE 1 fields ──────────────────────────────────────
    first_name: str = None,
    last_name: str = None,
    contact_number: str = None,
    # ── TYPE 2 fields ──────────────────────────────────────
    patient_id: int = None,
    appointment_id: int = None,
    date_of_birth: str = None,
    treatment_name: str = None,
    dentist_name: str = None,
    treatment_date: str = None,
    treatment_time: str = None,
    additional_info: str = None,
) -> dict:

    category = (complaint_category or "general").lower().strip()
    if category not in ("general", "treatment"):
        category = "general"

    if not complaint_text or not complaint_text.strip():
        return {"status": "MISSING_INFO", "message": "Complaint text is required."}

    # ── TYPE 1 validation ─────────────────────────────────
    if category == "general":
        if not all([first_name, last_name, contact_number]):
            missing = [
                f for f, v in [
                    ("first name", first_name),
                    ("last name", last_name),
                    ("contact number", contact_number),
                ]
                if not v
            ]
            return {
                "status": "MISSING_INFO",
                "message": f"Please provide: {', '.join(missing)}.",
            }
        patient_name_full = title_case(f"{first_name.strip()} {last_name.strip()}")
        norm_contact = normalize_phone(contact_number)
        contact_spoken = format_phone_for_speech(norm_contact)

        print(f"[COMPLAINT] TYPE 1 (general) — {patient_name_full}")
        try:
            with db_cursor() as (cursor, conn):
                cursor.execute(
                    """
                    INSERT INTO complaints
                        (complaint_category, patient_name, contact_number,
                         complaint_text, status)
                    VALUES (%s, %s, %s, %s, 'pending')
                    RETURNING complaint_id
                    """,
                    (category, patient_name_full, norm_contact, complaint_text.strip()),
                )
                conn.commit()
            return {
                "status": "SAVED",
                "complaint_category": "general",
                "patient_name": patient_name_full,
                "contact_spoken": contact_spoken,
                "message": (
                    f"Your complaint has been recorded, {first_name.strip().title()}. "
                    "I'll make sure our manager is informed right away. "
                    "We'll look into this and get back to you as soon as possible."
                ),
            }
        except Exception as e:
            traceback.print_exc()
            return {"status": "ERROR", "message": str(e)}

    # ── TYPE 2 validation ─────────────────────────────────
    else:
        if not patient_id:
            return {
                "status": "ERROR",
                "message": "Patient must be verified before filing a treatment complaint.",
            }

        print(f"[COMPLAINT] TYPE 2 (treatment) — patient_id={patient_id}")
        try:
            with db_cursor() as (cursor, conn):
                cursor.execute(
                    """
                    INSERT INTO complaints
                        (complaint_category, patient_id, appointment_id,
                         patient_name, date_of_birth, contact_number,
                         complaint_text, treatment_name, dentist_name,
                         treatment_date, treatment_time, additional_info, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending')
                    RETURNING complaint_id
                    """,
                    (
                        "treatment",
                        patient_id,
                        appointment_id,
                        title_case(f"{first_name or ''} {last_name or ''}").strip(),
                        date_of_birth,
                        normalize_phone(contact_number) if contact_number else None,
                        complaint_text.strip(),
                        treatment_name,
                        dentist_name,
                        treatment_date,
                        treatment_time,
                        additional_info,
                    ),
                )
                conn.commit()
            return {
                "status": "SAVED",
                "complaint_category": "treatment",
                "message": (
                    f"I've logged your complaint about the {treatment_name or 'treatment'}. "
                    "Our team will review everything and get back to you within 2 business days."
                ),
            }
        except Exception as e:
            traceback.print_exc()
            return {"status": "ERROR", "message": str(e)}


def get_complaints_by_patient_id(patient_id: int) -> dict:
    try:
        with db_cursor() as (cursor, conn):
            cursor.execute(
                """
                SELECT complaint_id, complaint_category, patient_name, contact_number,
                       complaint_text, treatment_name, dentist_name,
                       treatment_date, status, created_at
                FROM complaints WHERE patient_id = %s ORDER BY created_at DESC
                """,
                (patient_id,),
            )
            rows = cursor.fetchall()
        return {
            "status": "SUCCESS",
            "complaints": [
                {
                    "complaint_id": r[0], "category": r[1], "patient_name": r[2],
                    "contact_number": r[3], "complaint_text": r[4],
                    "treatment_name": r[5], "dentist_name": r[6],
                    "treatment_date": r[7], "status": r[8], "created_at": str(r[9]),
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}