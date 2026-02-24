"""
appointment/executor.py — DentalBot v2
All appointment DB operations matching the new schema.
"""

import re
from datetime import datetime, date, timedelta
from db.db_connection import get_db_connection, db_cursor


# ─────────────────────────────────────────────────────────────
# DENTISTS
# ─────────────────────────────────────────────────────────────

DENTISTS = [
    "Dr. Emily Carter",
    "Dr. James Nguyen",
    "Dr. Sarah Mitchell"
]


# ─────────────────────────────────────────────────────────────
# DATE / TIME PARSERS
# ─────────────────────────────────────────────────────────────

def parse_date_str(date_str: str) -> str:
    """
    Convert natural language date → YYYY-MM-DD string.
    Handles: "today", "tomorrow", "next Thursday",
             "coming Wednesday", "25th February", etc.
    """
    if not date_str:
        return None

    s = date_str.lower().strip()
    today = date.today()

    if "today" in s:
        return today.strftime("%Y-%m-%d")
    if "tomorrow" in s:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    day_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2,
        "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
    }
    for day_name, day_num in day_map.items():
        if day_name in s:
            diff = (day_num - today.weekday()) % 7
            if diff == 0:
                diff = 7   # "coming Thursday" when today IS Thursday → next week
            return (today + timedelta(days=diff)).strftime("%Y-%m-%d")

    # Try dateutil parser (handles "15th September 2005", "25 Feb 2026", etc.)
    try:
        from dateutil import parser as dp
        parsed = dp.parse(date_str, dayfirst=True, default=datetime(today.year, today.month, today.day))
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        pass

    # Try manual formats
    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y"]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_str   # return as-is if nothing matched


def parse_time_str(time_str: str) -> str:
    """
    Convert natural language time → HH:MM string.
    Handles: "11am", "2 pm", "11:30 AM", "14:00", etc.
    """
    if not time_str:
        return None

    s = time_str.lower().strip()

    # 24-hour format already
    match = re.match(r'^(\d{1,2}):(\d{2})$', s)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        return f"{h:02d}:{m:02d}"

    # 12-hour with optional minutes
    match = re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$', s)
    if match:
        h = int(match.group(1))
        m = int(match.group(2)) if match.group(2) else 0
        period = match.group(3)
        if period == "pm" and h != 12:
            h += 12
        elif period == "am" and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}"

    # Word-based: "morning" → 09:00, "afternoon" → 14:00, "evening" → 17:00
    if "morning"   in s: return "09:00"
    if "afternoon" in s: return "14:00"
    if "evening"   in s: return "17:00"

    return time_str


# ─────────────────────────────────────────────────────────────
# AVAILABILITY
# ─────────────────────────────────────────────────────────────

def check_dentist_availability(date_str: str, time_str: str,
                                dentist_name: str) -> dict:
    """
    Check if a specific dentist has a free slot at date + time.
    Returns: AVAILABLE | NOT_AVAILABLE | INVALID | ERROR
    """
    try:
        parsed_date = parse_date_str(date_str)
        parsed_time = parse_time_str(time_str)

        if not parsed_date or not parsed_time:
            return {
                "status":  "INVALID",
                "message": "Could not understand the date or time."
            }

        with db_cursor() as (cursor, conn):

            cursor.execute("""
                SELECT COUNT(*) FROM appointments
                WHERE LOWER(preferred_dentist) LIKE LOWER(%s)
                AND   preferred_date = %s
                AND   preferred_time = %s
                AND   status != 'cancelled'
            """, (f"%{dentist_name}%", parsed_date, parsed_time))

            count = cursor.fetchone()[0]

        if count > 0:
            return {
                "status":  "NOT_AVAILABLE",
                "dentist": dentist_name,
                "date":    parsed_date,
                "time":    parsed_time,
                "message": f"{dentist_name} already has an appointment at that time."
            }

        return {
            "status":  "AVAILABLE",
            "dentist": dentist_name,
            "date":    parsed_date,
            "time":    parsed_time
        }

    except Exception as e:
        print(f"[ERROR] check_dentist_availability: {e}")
        import traceback; traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


def find_available_dentist(date_str: str, time_str: str) -> dict:
    """
    Find first available dentist at given date + time.
    Returns: FOUND | NONE_AVAILABLE_SUGGEST | INVALID | ERROR
    """
    try:
        parsed_date = parse_date_str(date_str)
        parsed_time = parse_time_str(time_str)

        if not parsed_date or not parsed_time:
            return {
                "status":  "INVALID",
                "message": "Could not understand the date or time."
            }

        conn   = get_db_connection()
        cursor = conn.cursor()

        for dentist in DENTISTS:
            cursor.execute("""
                SELECT COUNT(*) FROM appointments
                WHERE LOWER(preferred_dentist) LIKE LOWER(%s)
                AND   preferred_date = %s
                AND   preferred_time = %s
                AND   status != 'cancelled'
            """, (f"%{dentist}%", parsed_date, parsed_time))

            count = cursor.fetchone()[0]

            if count == 0:
                cursor.close()
                conn.close()
                return {
                    "status":  "FOUND",
                    "dentist": dentist,
                    "date":    parsed_date,
                    "time":    parsed_time
                }

        cursor.close()
        conn.close()

        # No dentist free — suggest next day same time
        try:
            next_day = (
                datetime.strptime(parsed_date, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
        except Exception:
            next_day = parsed_date

        return {
            "status":         "NONE_AVAILABLE_SUGGEST",
            "suggested_date": next_day,
            "suggested_time": parsed_time,
            "message": (
                f"No dentists available on {parsed_date} at {parsed_time}. "
                f"Next available day is {next_day}."
            )
        }

    except Exception as e:
        print(f"[ERROR] find_available_dentist: {e}")
        import traceback; traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────
# BOOKING
# ─────────────────────────────────────────────────────────────

def book_appointment(patient_id: int, first_name: str, last_name: str,
                     date_of_birth: str, contact_number: str,
                     preferred_treatment: str, preferred_date: str,
                     preferred_time: str, preferred_dentist: str) -> dict:
    """
    Insert a confirmed appointment into the DB.
    Returns: BOOKED | ERROR
    """
    try:
        parsed_date = parse_date_str(preferred_date)
        parsed_time = parse_time_str(preferred_time)

        print(f"[DB] Booking → patient_id={patient_id} "
              f"date={parsed_date} time={parsed_time} "
              f"dentist={preferred_dentist} treatment={preferred_treatment}")

        conn   = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO appointments
                (patient_id, first_name, last_name, date_of_birth,
                 contact_number, preferred_treatment, preferred_date,
                 preferred_time, preferred_dentist, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'confirmed')
            RETURNING appointment_id
        """, (
            patient_id,
            first_name,
            last_name,
            date_of_birth,
            contact_number,
            preferred_treatment,
            parsed_date,
            parsed_time,
            preferred_dentist
        ))

        appt_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()

        print(f"[DB] ✅ Appointment saved — ID {appt_id}")

        return {
            "status":         "BOOKED",
            "appointment_id": appt_id,    # internal only — NOT passed to LLM
            "treatment":      preferred_treatment,
            "date":           parsed_date,
            "time":           parsed_time,
            "dentist":        preferred_dentist
        }

    except Exception as e:
        print(f"[ERROR] book_appointment: {e}")
        import traceback; traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────
# FETCH
# ─────────────────────────────────────────────────────────────

def get_patient_appointments(patient_id: int) -> dict:
    """
    Get all active (non-cancelled) appointments for a patient.
    Returns list ordered by date ASC.
    """
    try:
        with db_cursor() as (cursor, conn):

            cursor.execute("""
                SELECT appointment_id, preferred_treatment,
                    preferred_date, preferred_time,
                    preferred_dentist, status
                FROM appointments
                WHERE patient_id = %s
                AND   status NOT IN ('cancelled', 'completed')
                ORDER BY preferred_date ASC, preferred_time ASC
            """, (patient_id,))

            rows = cursor.fetchall()

        if not rows:
            return {
                "status":       "NO_APPOINTMENTS",
                "appointments": [],
                "count":        0
            }

        appointments = []
        for row in rows:
            appointments.append({
                "_id":       row[0],          # internal ID — never shown to LLM
                "treatment": row[1],
                "date":      str(row[2]),
                "time":      str(row[3]),
                "dentist":   row[4],
                "status":    row[5]
            })

        return {
            "status":       "SUCCESS",
            "appointments": appointments,
            "count":        len(appointments)
        }

    except Exception as e:
        print(f"[ERROR] get_patient_appointments: {e}")
        import traceback; traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────
# UPDATE
# ─────────────────────────────────────────────────────────────

def update_appointment(appointment_id: int, update_fields: dict) -> dict:
    """
    Update one or more fields of an existing appointment.
    """
    try:
        field_map = {
            "preferred_treatment": None,
            "preferred_date":      "date",
            "preferred_time":      "time",
            "preferred_dentist":   None
        }

        set_clauses = []
        values      = []

        if update_fields.get("preferred_treatment"):
            set_clauses.append("preferred_treatment = %s")
            values.append(update_fields["preferred_treatment"])

        if update_fields.get("preferred_date"):
            set_clauses.append("preferred_date = %s")
            values.append(parse_date_str(update_fields["preferred_date"]))

        if update_fields.get("preferred_time"):
            set_clauses.append("preferred_time = %s")
            values.append(parse_time_str(update_fields["preferred_time"]))

        if update_fields.get("preferred_dentist"):
            set_clauses.append("preferred_dentist = %s")
            values.append(update_fields["preferred_dentist"])

        if not set_clauses:
            return {"status": "ERROR", "message": "No fields to update."}

        values.append(appointment_id)

        with db_cursor() as (cursor, conn):

            cursor.execute(f"""
                UPDATE appointments
                SET {', '.join(set_clauses)}
                WHERE appointment_id = %s
                RETURNING preferred_treatment, preferred_date,
                        preferred_time, preferred_dentist
            """, values)

            row = cursor.fetchone()
        conn.commit()

        if row:
            return {
                "status":    "UPDATED",
                "treatment": row[0],
                "date":      str(row[1]),
                "time":      str(row[2]),
                "dentist":   row[3]
            }

        return {"status": "ERROR", "message": "Appointment not found."}

    except Exception as e:
        print(f"[ERROR] update_appointment: {e}")
        import traceback; traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────
# CANCEL
# ─────────────────────────────────────────────────────────────

def cancel_appointment(appointment_id: int, reason: str = None) -> dict:
    """Cancel an appointment by ID."""
    try:
        with db_cursor() as (cursor, conn):

            cursor.execute("""
                UPDATE appointments
                SET status = 'cancelled'
                WHERE appointment_id = %s
                RETURNING preferred_treatment, preferred_date,
                        preferred_time, preferred_dentist
            """, (appointment_id,))

            row = cursor.fetchone()
        conn.commit()

        if row:
            return {
                "status":    "CANCELLED",
                "treatment": row[0],
                "date":      str(row[1]),
                "time":      str(row[2]),
                "dentist":   row[3]
            }

        return {"status": "ERROR", "message": "Appointment not found."}

    except Exception as e:
        print(f"[ERROR] cancel_appointment: {e}")
        import traceback; traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}
