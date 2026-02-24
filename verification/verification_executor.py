"""
Verification Executor - DentalBot v2
Handles all DB operations for patient verification and account creation.
No patient_id is ever returned to the caller for display.
"""

from db.db_connection import get_db_connection, db_cursor
from utils.phone_utils import normalize_phone
from utils.text_utils import title_case
from utils.date_time_utils import dob_to_db_format


# ─────────────────────────────────────────────────────────────────────────────
# VERIFY EXISTING PATIENT
# ─────────────────────────────────────────────────────────────────────────────

def verify_by_lastname_dob(last_name: str, dob: str) -> dict:
    """
    Verify a patient using last_name + DOB.

    Returns:
        status = VERIFIED       → exactly 1 match found
        status = MULTIPLE_FOUND → more than 1 match (ask contact number)
        status = NOT_FOUND      → no match
        status = ERROR          → DB error
    """
    if not last_name or not dob:
        return {
            "status": "MISSING_INFO",
            "message": "Last name and date of birth are both required."
        }

    dob_clean      = dob_to_db_format(dob)
    last_name_clean = last_name.strip().lower()

    try:
        with db_cursor() as (cursor, conn):

            cursor.execute("""
                SELECT patient_id, first_name, last_name,
                    date_of_birth, contact_number, insurance_info
                FROM patients
                WHERE LOWER(last_name) = %s
                AND date_of_birth    = %s
            """, (last_name_clean, dob_clean))

            rows = cursor.fetchall()

        if not rows:
            return {
                "status": "NOT_FOUND",
                "message": (
                    "I'm sorry, I couldn't find any account with that last name "
                    "and date of birth. Please check your details or let me know "
                    "if you'd like to create a new account."
                )
            }

        if len(rows) > 1:
            return {
                "status": "MULTIPLE_FOUND",
                "message": (
                    "I found more than one account with that name and date of birth. "
                    "Could you please provide your contact number so I can confirm "
                    "which account is yours?"
                ),
                "count": len(rows)
            }

        row = rows[0]
        return {
            "status":         "VERIFIED",
            "patient_id":     row[0],           # internal only — never shown to user
            "first_name":     title_case(row[1]),
            "last_name":      title_case(row[2]),
            "date_of_birth":  row[3],
            "contact_number": row[4],
            "insurance_info": row[5]
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


def verify_by_lastname_dob_contact(
    last_name: str,
    dob: str,
    contact_number: str
) -> dict:
    """
    Disambiguate when multiple patients share the same last_name + DOB.
    Uses contact_number to find the correct record.
    """
    dob_clean       = dob_to_db_format(dob)
    last_name_clean = last_name.strip().lower()
    contact_clean   = normalize_phone(contact_number)

    try:
        with db_cursor() as (cursor, conn):

            cursor.execute("""
                SELECT patient_id, first_name, last_name,
                    date_of_birth, contact_number, insurance_info
                FROM patients
                WHERE LOWER(last_name) = %s
                AND date_of_birth    = %s
            """, (last_name_clean, dob_clean))

            rows = cursor.fetchall()

        for row in rows:
            if normalize_phone(row[4]) == contact_clean:
                return {
                    "status":         "VERIFIED",
                    "patient_id":     row[0],
                    "first_name":     title_case(row[1]),
                    "last_name":      title_case(row[2]),
                    "date_of_birth":  row[3],
                    "contact_number": row[4],
                    "insurance_info": row[5]
                }

        return {
            "status": "NOT_FOUND",
            "message": (
                "I'm sorry, I still couldn't verify your account with those details. "
                "Please double-check your information or contact us directly for assistance."
            )
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# CREATE NEW PATIENT
# ─────────────────────────────────────────────────────────────────────────────

def create_new_patient(
    first_name:     str,
    last_name:      str,
    dob:            str,
    contact_number: str,
    insurance_info: str = None
) -> dict:
    """
    Create a new patient record.
    Returns patient data on success.
    patient_id is stored internally — never exposed to the user.
    """
    if not all([first_name, last_name, dob, contact_number]):
        return {
            "status":  "MISSING_INFO",
            "message": "First name, last name, date of birth, and contact number are all required."
        }

    dob_clean     = dob_to_db_format(dob)
    contact_clean = normalize_phone(contact_number)

    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO patients
                (first_name, last_name, date_of_birth, contact_number, insurance_info)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING patient_id
        """, (
            title_case(first_name),
            title_case(last_name),
            dob_clean,
            contact_clean,
            insurance_info
        ))

        patient_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()

        return {
            "status":         "CREATED",
            "patient_id":     patient_id,       # internal only
            "first_name":     title_case(first_name),
            "last_name":      title_case(last_name),
            "date_of_birth":  dob_clean,
            "contact_number": contact_clean,
            "insurance_info": insurance_info
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


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
