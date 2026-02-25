"""
Complaint Executor - DentalBot v2
Old logic + new db_cursor() syntax.
"""

from db.db_connection import db_cursor
from utils.text_utils import title_case
from utils.phone_utils import normalize_phone, format_phone_for_speech
import traceback


# ─────────────────────────────────────────────────────────────────────────────
# SAVE COMPLAINT
# ─────────────────────────────────────────────────────────────────────────────

def save_complaint(
    patient_name:       str,
    contact_number:     str,
    complaint_text:     str,
    complaint_category: str,
    treatment_name:     str = None,
    dentist_name:       str = None,
    treatment_date:     str = None
) -> dict:

    # ✅ Input validation — never save incomplete complaint
    if not all([patient_name, contact_number, complaint_text, complaint_category]):
        return {
            "status":  "MISSING_INFO",
            "message": "Patient name, contact, complaint text, and category are required."
        }

    # ✅ Normalize category
    category = complaint_category.lower()
    if category not in ("general", "treatment"):
        category = "general"

    print(f"[COMPLAINT] Saving for: {patient_name} | Category: {category}")
    print(f"[COMPLAINT] Text: {complaint_text}")

    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("""
                INSERT INTO complaints (
                    complaint_category,
                    patient_name,
                    contact_number,
                    complaint_text,
                    treatment_name,
                    dentist_name,
                    treatment_date,
                    status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                RETURNING complaint_id
            """, (
                category,
                title_case(patient_name),          # ✅ title case
                normalize_phone(contact_number),   # ✅ normalize phone
                complaint_text.strip(),            # ✅ strip whitespace
                treatment_name,
                dentist_name,
                treatment_date
            ))
            _ = cursor.fetchone()[0]   # complaint_id — internal only, never shown

        contact_spoken = format_phone_for_speech(normalize_phone(contact_number))
        print("[COMPLAINT] ✅ Saved successfully")

        return {
            "status":             "SAVED",
            "patient_name":       title_case(patient_name),
            "contact_spoken":     contact_spoken,
            "complaint_category": category,
            "message": (
                f"Complaint recorded successfully. "
                f"Management will contact {title_case(patient_name)} "
                f"on {contact_spoken} within 2 business days."
            )
        }

    except Exception as e:
        print("[COMPLAINT] ❌ Failed to save:")
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# FETCH COMPLAINTS BY PATIENT (management portal only)
# ─────────────────────────────────────────────────────────────────────────────

def get_complaints_by_name(patient_name: str) -> dict:
    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("""
                SELECT
                    complaint_id, complaint_category, patient_name,
                    contact_number, complaint_text, treatment_name,
                    dentist_name, treatment_date, status, created_at
                FROM complaints
                WHERE LOWER(patient_name) LIKE LOWER(%s)
                ORDER BY created_at DESC
            """, (f"%{patient_name.strip()}%",))
            rows = cursor.fetchall()

        return {
            "status": "SUCCESS",
            "complaints": [
                {
                    "complaint_id":   r[0],
                    "category":       r[1],
                    "patient_name":   r[2],
                    "contact_number": r[3],
                    "complaint_text": r[4],
                    "treatment_name": r[5],
                    "dentist_name":   r[6],
                    "treatment_date": r[7],
                    "status":         r[8],
                    "created_at":     str(r[9])
                } for r in rows
            ],
            "count": len(rows)
        }

    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}
