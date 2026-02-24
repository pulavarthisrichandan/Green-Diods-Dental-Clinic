"""
Complaint Executor - DentalBot v2

All DB operations for saving and retrieving complaints.
Two categories: 'general' and 'treatment'.

complaint_id is INTERNAL — never returned to or spoken to the patient.
Patient details always come from the verified session.
"""

from db.db_connection import db_cursor
from utils.text_utils import title_case
from utils.phone_utils import normalize_phone, format_phone_for_speech


# ─────────────────────────────────────────────────────────────────────────────
# SAVE COMPLAINT
# ─────────────────────────────────────────────────────────────────────────────

from db.db_connection import db_cursor

def save_complaint(patient_name, contact_number, complaint_text,
                   complaint_category="general",
                   treatment_name=None, dentist_name=None, treatment_date=None):
    
    """
    Save a patient complaint to the DB.

    All patient details come from the verified session —
    never collected again from the user.

    Returns:
        status = SAVED   → success (complaint_id internal only)
        status = ERROR   → DB error
    """

    with db_cursor() as (cursor, conn):
        cursor.execute("""
            INSERT INTO complaints
            (patient_name, contact_number, complaint_text,
             complaint_category, treatment_name, dentist_name, treatment_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            patient_name, contact_number, complaint_text,
            complaint_category, treatment_name, dentist_name, treatment_date
        ))

    return {"status": "SAVED"}
    



# ─────────────────────────────────────────────────────────────────────────────
# FETCH COMPLAINTS BY PATIENT (management portal use only)
# ─────────────────────────────────────────────────────────────────────────────

def get_complaints_by_name(patient_name: str) -> dict:
    """
    Internal use only — used by management portal.
    Never called in response to a patient phone call.
    """
    try:
        with db_cursor() as (cursor, conn):

            cursor.execute("""
                SELECT
                    complaint_id,
                    complaint_category,
                    patient_name,
                    contact_number,
                    complaint_text,
                    treatment_name,
                    dentist_name,
                    treatment_date,
                    status,
                    created_at
                FROM complaints
                WHERE LOWER(patient_name) LIKE LOWER(%s)
                ORDER BY created_at DESC
            """, (f"%{patient_name.strip()}%",))

            rows = cursor.fetchall()

        complaints = []
        for row in rows:
            complaints.append({
                "complaint_id":       row[0],
                "category":           row[1],
                "patient_name":       row[2],
                "contact_number":     row[3],
                "complaint_text":     row[4],
                "treatment_name":     row[5],
                "dentist_name":       row[6],
                "treatment_date":     row[7],
                "status":             row[8],
                "created_at":         str(row[9])
            })

        return {"status": "SUCCESS", "complaints": complaints, "count": len(complaints)}

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}
