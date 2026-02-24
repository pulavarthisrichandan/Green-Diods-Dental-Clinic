"""
Verification Executor - DentalBot v2
Handles all DB operations for patient verification and account creation.
No patient_id is ever returned to the caller for display.
"""

from db.db_connection import db_cursor
from utils.phone_utils import normalize_phone
from utils.text_utils import title_case
from utils.date_time_utils import dob_to_db_format


# ─────────────────────────────────────────────────────────────────────────────
# VERIFY EXISTING PATIENT
# ─────────────────────────────────────────────────────────────────────────────

def verify_by_lastname_dob(last_name, dob):
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT patient_id, first_name, last_name, date_of_birth, contact_number
            FROM patients
            WHERE last_name = %s AND date_of_birth = %s
        """, (last_name, dob))
        rows = cursor.fetchall()

    if not rows:
        return {"status": "NOT_FOUND"}

    if len(rows) == 1:
        r = rows[0]
        return {
            "status": "VERIFIED",
            "patient_id": r[0],
            "first_name": r[1],
            "last_name": r[2],
            "date_of_birth": str(r[3]),
            "contact_number": r[4]
        }

    return {"status": "MULTIPLE_FOUND", "message": "Multiple records found. Please provide contact number."}


def verify_by_lastname_dob_contact(last_name, dob, contact_number):
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT patient_id, first_name, last_name, date_of_birth, contact_number
            FROM patients
            WHERE last_name = %s AND date_of_birth = %s AND contact_number = %s
        """, (last_name, dob, contact_number))
        row = cursor.fetchone()

    if not row:
        return {"status": "NOT_FOUND"}

    return {
        "status": "VERIFIED",
        "patient_id": row[0],
        "first_name": row[1],
        "last_name": row[2],
        "date_of_birth": str(row[3]),
        "contact_number": row[4]
    }


# ─────────────────────────────────────────────────────────────────────────────
# CREATE NEW PATIENT
# ─────────────────────────────────────────────────────────────────────────────

def create_new_patient(first_name, last_name, dob, contact_number, insurance_info=None):
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            INSERT INTO patients
            (first_name, last_name, date_of_birth, contact_number, insurance_info)
            VALUES (%s,%s,%s,%s,%s)
            RETURNING patient_id
        """, (first_name, last_name, dob, contact_number, insurance_info))
        pid = cursor.fetchone()[0]

    return {
        "status": "CREATED",
        "patient_id": pid,
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": dob,
        "contact_number": contact_number
    }


# ─────────────────────────────────────────────────────────────────────────────
# FETCH PATIENT BY ID (internal use only)
# ─────────────────────────────────────────────────────────────────────────────

def get_patient_by_id(patient_id: int) -> dict:
    """
    Internal lookup — used by other modules after verification is already done.
    Never call this in response to user input.
    """
    try:
        with db_cursor() as (cursor, conn):

            cursor.execute("""
                SELECT patient_id, first_name, last_name,
                    date_of_birth, contact_number, insurance_info
                FROM patients
                WHERE patient_id = %s
            """, (patient_id,))

            row = cursor.fetchone()

        if not row:
            return {"status": "NOT_FOUND"}

        return {
            "status":         "FOUND",
            "patient_id":     row[0],
            "first_name":     title_case(row[1]),
            "last_name":      title_case(row[2]),
            "date_of_birth":  row[3],
            "contact_number": row[4],
            "insurance_info": row[5]
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}
