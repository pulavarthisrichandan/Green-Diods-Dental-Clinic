"""
appointment/executor.py — DentalBot v2
All appointment DB operations matching the new schema.
"""

import re
from datetime import datetime, date, timedelta
from db.db_connection import db_cursor


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

def check_dentist_availability(date_str, time_str, dentist_name):
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT COUNT(*) FROM appointments
            WHERE preferred_date = %s
              AND preferred_time = %s
              AND preferred_dentist = %s
              AND status = 'confirmed'
        """, (date_str, time_str, dentist_name))
        count = cursor.fetchone()[0]

    if count > 0:
        return {"status": "UNAVAILABLE"}
    return {"status": "AVAILABLE"}

    


def find_available_dentist(date_str, time_str):
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT dentist_name FROM dentists
            WHERE dentist_name NOT IN (
                SELECT preferred_dentist FROM appointments
                WHERE preferred_date = %s
                  AND preferred_time = %s
                  AND status = 'confirmed'
            )
            LIMIT 1
        """, (date_str, time_str))
        row = cursor.fetchone()

    if row:
        return {"status": "AVAILABLE", "dentist": row[0]}
    return {"status": "UNAVAILABLE"}


# ─────────────────────────────────────────────────────────────
# BOOKING
# ─────────────────────────────────────────────────────────────

def book_appointment(patient_id, first_name, last_name, date_of_birth,
                     contact_number, preferred_treatment,
                     preferred_date, preferred_time, preferred_dentist):

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
            preferred_date, preferred_time, preferred_dentist
        ))
        appt_id = cursor.fetchone()[0]

    return {
        "status": "BOOKED",
        "appointment_id": appt_id,
        "treatment": preferred_treatment,
        "date": preferred_date,
        "time": preferred_time,
        "dentist": preferred_dentist
    }


# ─────────────────────────────────────────────────────────────
# FETCH
# ─────────────────────────────────────────────────────────────

def get_patient_appointments(patient_id):
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT appointment_id, preferred_treatment,
                   preferred_date, preferred_time,
                   preferred_dentist, status
            FROM appointments
            WHERE patient_id = %s
            ORDER BY preferred_date DESC
        """, (patient_id,))
        rows = cursor.fetchall()

    appts = [
        {
            "_id": r[0],
            "treatment": r[1],
            "date": str(r[2]),
            "time": str(r[3]),
            "dentist": r[4],
            "status": r[5]
        } for r in rows
    ]

    return {"status": "SUCCESS", "appointments": appts}


# ─────────────────────────────────────────────────────────────
# UPDATE
# ─────────────────────────────────────────────────────────────

def update_appointment(appointment_id, fields: dict):
    if not fields:
        return {"status": "ERROR", "message": "No fields to update"}

    set_clause = ", ".join([f"{k} = %s" for k in fields.keys()])
    values = list(fields.values()) + [appointment_id]

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
        return {"status": "ERROR", "message": "Appointment not found"}

    return {
        "status": "UPDATED",
        "treatment": row[0],
        "date": str(row[1]),
        "time": str(row[2]),
        "dentist": row[3]
    }


# ─────────────────────────────────────────────────────────────
# CANCEL
# ─────────────────────────────────────────────────────────────

def cancel_appointment(appointment_id, reason=None):
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
        return {"status": "ERROR", "message": "Appointment not found"}

    return {
        "status": "CANCELLED",
        "treatment": row[0],
        "date": str(row[1]),
        "time": str(row[2]),
        "dentist": row[3]
    }
