"""
General Enquiry Executor - DentalBot v2
Old try/except logic + new db_cursor() syntax.
"""

from db.db_connection import db_cursor
import traceback


# ─────────────────────────────────────────────────────────────────────────────
# ORDER STATUS
# ─────────────────────────────────────────────────────────────────────────────

def get_patient_orders(patient_id):
    try:
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

    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# UPCOMING APPOINTMENTS
# ─────────────────────────────────────────────────────────────────────────────

def get_upcoming_appointments(patient_id):
    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("""
                SELECT preferred_treatment, preferred_date,
                       preferred_time, preferred_dentist
                FROM appointments
                WHERE patient_id     = %s
                  AND preferred_date >= CURRENT_DATE
                  AND status          = 'confirmed'
                ORDER BY preferred_date ASC, preferred_time ASC
            """, (patient_id,))
            rows = cursor.fetchall()

        return {
            "status": "SUCCESS",
            "appointments": [
                {
                    "treatment": r[0],
                    "date":      str(r[1]),
                    "time":      str(r[2]),
                    "dentist":   r[3]
                } for r in rows
            ],
            "count": len(rows)
        }

    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# PAST APPOINTMENTS / TREATMENT HISTORY
# ─────────────────────────────────────────────────────────────────────────────

def get_past_appointments(patient_id):
    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("""
                SELECT preferred_treatment, preferred_date, preferred_dentist
                FROM appointments
                WHERE patient_id     = %s
                  AND preferred_date  < CURRENT_DATE
                ORDER BY preferred_date DESC
            """, (patient_id,))
            rows = cursor.fetchall()

        return {
            "status": "SUCCESS",
            "appointments": [
                {
                    "treatment": r[0],
                    "date":      str(r[1]),
                    "dentist":   r[2]
                } for r in rows
            ],
            "count": len(rows)
        }

    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}
