"""
appointment/executor.py — DentalBot v2
New date/time parsers + old try/except logic on all DB functions.
"""

import re
import traceback
from datetime import datetime, date, timedelta
from db.db_connection import db_cursor


DENTISTS = [
    "Dr. Emily Carter",
    "Dr. James Nguyen",
    "Dr. Sarah Mitchell"
]


# ─────────────────────────────────────────────────────────────────────────────
# DATE / TIME PARSERS
# ─────────────────────────────────────────────────────────────────────────────

def parse_date_str(date_str: str) -> str:
    if not date_str:
        return None

    s     = date_str.lower().strip()
    today = date.today()

    if "today"    in s: return today.strftime("%Y-%m-%d")
    if "tomorrow" in s: return (today + timedelta(days=1)).strftime("%Y-%m-%d")

    day_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2,
        "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
    }
    for day_name, day_num in day_map.items():
        if day_name in s:
            diff = (day_num - today.weekday()) % 7
            if diff == 0:
                diff = 7
            return (today + timedelta(days=diff)).strftime("%Y-%m-%d")

    try:
        from dateutil import parser as dp
        parsed = dp.parse(date_str, dayfirst=True,
                          default=datetime(today.year, today.month, today.day))
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        pass

    for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y"]:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_str


def parse_time_str(time_str: str) -> str:
    if not time_str:
        return None

    s = time_str.lower().strip()

    match = re.match(r'^(\d{1,2}):(\d{2})$', s)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        return f"{h:02d}:{m:02d}"

    match = re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$', s)
    if match:
        h      = int(match.group(1))
        m      = int(match.group(2)) if match.group(2) else 0
        period = match.group(3)
        if period == "pm" and h != 12: h += 12
        elif period == "am" and h == 12: h = 0
        return f"{h:02d}:{m:02d}"

    if "morning"   in s: return "09:00"
    if "afternoon" in s: return "14:00"
    if "evening"   in s: return "17:00"

    return time_str


# ─────────────────────────────────────────────────────────────────────────────
# AVAILABILITY
# ─────────────────────────────────────────────────────────────────────────────

def check_dentist_availability(date_str, time_str, dentist_name):
    parsed_date = parse_date_str(date_str)
    parsed_time = parse_time_str(time_str)

    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("""
                SELECT COUNT(*) FROM appointments
                WHERE preferred_date    = %s
                  AND preferred_time    = %s
                  AND preferred_dentist = %s
                  AND status            = 'confirmed'
            """, (parsed_date, parsed_time, dentist_name))
            count = cursor.fetchone()[0]

        if count > 0:
            return {
                "status":       "UNAVAILABLE",
                "dentist":      dentist_name,
                "date":         parsed_date,
                "time":         parsed_time,
                "message":      f"{dentist_name} is not available at that time."
            }
        return {
            "status":  "AVAILABLE",
            "dentist": dentist_name,
            "date":    parsed_date,
            "time":    parsed_time
        }

    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


def find_available_dentist(date_str, time_str):
    parsed_date = parse_date_str(date_str)
    parsed_time = parse_time_str(time_str)

    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("""
                SELECT dentist_name FROM dentists
                WHERE dentist_name NOT IN (
                    SELECT preferred_dentist FROM appointments
                    WHERE preferred_date = %s
                      AND preferred_time = %s
                      AND status         = 'confirmed'
                )
                LIMIT 1
            """, (parsed_date, parsed_time))
            row = cursor.fetchone()

        if row:
            return {
                "status":  "AVAILABLE",
                "dentist": row[0],
                "date":    parsed_date,
                "time":    parsed_time
            }
        return {
            "status":  "UNAVAILABLE",
            "message": "No dentists available at that date and time."
        }

    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# BOOKING
# ─────────────────────────────────────────────────────────────────────────────

def book_appointment(patient_id, first_name, last_name, date_of_birth,
                     contact_number, preferred_treatment,
                     preferred_date, preferred_time, preferred_dentist):

    parsed_date = parse_date_str(preferred_date)
    parsed_time = parse_time_str(preferred_time)

    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("""
                INSERT INTO appointments
                (patient_id, first_name, last_name, date_of_birth,
                 contact_number, preferred_treatment, preferred_date,
                 preferred_time, preferred_dentist, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'confirmed')
                RETURNING appointment_id
            """, (
                patient_id, first_name, last_name, date_of_birth,
                contact_number, preferred_treatment,
                parsed_date, parsed_time, preferred_dentist
            ))
            appt_id = cursor.fetchone()[0]

        return {
            "status":         "BOOKED",
            "appointment_id": appt_id,
            "treatment":      preferred_treatment,
            "date":           parsed_date,
            "time":           parsed_time,
            "dentist":        preferred_dentist
        }

    except Exception as e:
        print("[APPOINTMENT] ❌ book_appointment failed:")
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# FETCH ALL APPOINTMENTS
# ─────────────────────────────────────────────────────────────────────────────

def get_patient_appointments(patient_id):
    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("""
                SELECT appointment_id, preferred_treatment,
                       preferred_date, preferred_time,
                       preferred_dentist, status
                FROM appointments
                WHERE patient_id = %s
                  AND status     = 'confirmed'
                ORDER BY preferred_date ASC
            """, (patient_id,))
            rows = cursor.fetchall()

        return {
            "status": "SUCCESS",
            "appointments": [
                {
                    "_id":       r[0],
                    "treatment": r[1],
                    "date":      str(r[2]),
                    "time":      str(r[3]),
                    "dentist":   r[4],
                    "status":    r[5]
                } for r in rows
            ]
        }

    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE
# ─────────────────────────────────────────────────────────────────────────────

def update_appointment(appointment_id, fields: dict):
    if not fields:
        return {"status": "ERROR", "message": "No fields to update."}

    # Parse date/time if provided
    if "preferred_date" in fields:
        fields["preferred_date"] = parse_date_str(fields["preferred_date"])
    if "preferred_time" in fields:
        fields["preferred_time"] = parse_time_str(fields["preferred_time"])

    set_clause = ", ".join([f"{k} = %s" for k in fields.keys()])
    values     = list(fields.values()) + [appointment_id]

    try:
        with db_cursor() as (cursor, conn):
            cursor.execute(f"""
                UPDATE appointments
                SET {set_clause}
                WHERE appointment_id = %s
                RETURNING preferred_treatment, preferred_date,
                          preferred_time, preferred_dentist
            """, values)
            row = cursor.fetchone()

        if not row:
            return {"status": "ERROR", "message": "Appointment not found."}

        return {
            "status":    "UPDATED",
            "treatment": row[0],
            "date":      str(row[1]),
            "time":      str(row[2]),
            "dentist":   row[3]
        }

    except Exception as e:
        print("[APPOINTMENT] ❌ update_appointment failed:")
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# CANCEL
# ─────────────────────────────────────────────────────────────────────────────

def cancel_appointment(appointment_id, reason=None):
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

        if not row:
            return {"status": "ERROR", "message": "Appointment not found."}

        return {
            "status":    "CANCELLED",
            "treatment": row[0],
            "date":      str(row[1]),
            "time":      str(row[2]),
            "dentist":   row[3]
        }

    except Exception as e:
        print("[APPOINTMENT] ❌ cancel_appointment failed:")
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}
