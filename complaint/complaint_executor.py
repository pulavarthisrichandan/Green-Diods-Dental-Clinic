"""
Complaint Executor - DentalBot v2

All DB operations for saving and retrieving complaints.
Two categories: 'general' and 'treatment'.

complaint_id is INTERNAL — never returned to or spoken to the patient.
Patient details always come from the verified session.
"""

from db.db_connection import get_db_connection
from utils.text_utils import title_case
from utils.phone_utils import normalize_phone, format_phone_for_speech


# ─────────────────────────────────────────────────────────────────────────────
# SAVE COMPLAINT
# ─────────────────────────────────────────────────────────────────────────────

def save_complaint(
    patient_name:       str,
    contact_number:     str,
    complaint_text:     str,
    complaint_category: str,          # 'general' or 'treatment'
    treatment_name:     str = None,   # treatment complaints only
    dentist_name:       str = None,   # treatment complaints only (optional)
    treatment_date:     str = None    # treatment complaints only (optional, DD-MM-YYYY)
) -> dict:
    """
    Save a patient complaint to the DB.

    All patient details come from the verified session —
    never collected again from the user.

    Returns:
        status = SAVED   → success (complaint_id internal only)
        status = ERROR   → DB error
    """
    if not all([patient_name, contact_number, complaint_text, complaint_category]):
        return {
            "status":  "MISSING_INFO",
            "message": "Patient name, contact, complaint text, and category are required."
        }

    category = complaint_category.lower()
    if category not in ("general", "treatment"):
        category = "general"

    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

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
            title_case(patient_name),
            normalize_phone(contact_number),
            complaint_text.strip(),
            treatment_name,
            dentist_name,
            treatment_date
        ))

        # complaint_id → stored internally, never returned to caller
        _ = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()

        contact_spoken = format_phone_for_speech(normalize_phone(contact_number))

        return {
            "status":          "SAVED",
            "patient_name":    title_case(patient_name),
            "contact_spoken":  contact_spoken,
            "complaint_category": category,
            "message":         (
                f"Complaint recorded successfully. "
                f"Management will contact {title_case(patient_name)} "
                f"on {contact_spoken} within 2 business days."
            )
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# FETCH COMPLAINTS BY PATIENT (management portal use only)
# ─────────────────────────────────────────────────────────────────────────────

def get_complaints_by_name(patient_name: str) -> dict:
    """
    Internal use only — used by management portal.
    Never called in response to a patient phone call.
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

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
        cursor.close()
        conn.close()

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
