"""
General Enquiry Executor - DentalBot v2

DB lookups for:
    - Patient order status        → patient_orders table
    - Upcoming appointments       → appointments table
    - Past/completed appointments → appointments table

All lookups use patient_id from the verified session.
order_id, appointment_id are INTERNAL — never shown to patient.
"""

from db.db_connection import db_cursor
from utils.date_time_utils import parse_date, parse_time, format_date_for_speech, format_time_for_speech
from utils.text_utils import title_case
from datetime import date


# ─────────────────────────────────────────────────────────────────────────────
# ORDER STATUS ENQUIRY
# ─────────────────────────────────────────────────────────────────────────────

def get_patient_orders(patient_id):
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT product_name, order_status, notes
            FROM patient_orders
            WHERE patient_id = %s
            ORDER BY placed_at DESC
        """, (patient_id,))
        rows = cursor.fetchall()

    return {
        "status": "SUCCESS",
        "orders": [
            {"product_name": r[0], "order_status": r[1], "status_text": r[2]}
            for r in rows
        ],
        "count": len(rows)
    }

# ─────────────────────────────────────────────────────────────────────────────
# UPCOMING APPOINTMENTS
# ─────────────────────────────────────────────────────────────────────────────

def get_upcoming_appointments(patient_id):
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT preferred_treatment, preferred_date, preferred_time, preferred_dentist
            FROM appointments
            WHERE patient_id = %s AND preferred_date >= CURRENT_DATE
            ORDER BY preferred_date, preferred_time
        """, (patient_id,))
        rows = cursor.fetchall()

    return {
        "status": "SUCCESS",
        "appointments": [
            {"treatment": r[0], "date": str(r[1]), "time": str(r[2]), "dentist": r[3]}
            for r in rows
        ],
        "count": len(rows)
    }


# ─────────────────────────────────────────────────────────────────────────────
# PAST APPOINTMENTS / TREATMENT HISTORY
# ─────────────────────────────────────────────────────────────────────────────

def get_past_appointments(patient_id):
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT preferred_treatment, preferred_date, preferred_dentist
            FROM appointments
            WHERE patient_id = %s AND preferred_date < CURRENT_DATE
            ORDER BY preferred_date DESC
        """, (patient_id,))
        rows = cursor.fetchall()

    return {
        "status": "SUCCESS",
        "appointments": [
            {"treatment": r[0], "date": str(r[1]), "dentist": r[2]}
            for r in rows
        ],
        "count": len(rows)
    }
