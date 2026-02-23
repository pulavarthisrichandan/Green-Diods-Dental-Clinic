"""
General Enquiry Executor - DentalBot v2

DB lookups for:
    - Patient order status        → patient_orders table
    - Upcoming appointments       → appointments table
    - Past/completed appointments → appointments table

All lookups use patient_id from the verified session.
order_id, appointment_id are INTERNAL — never shown to patient.
"""

from db.db_connection import get_db_connection
from utils.date_time_utils import parse_date, parse_time, format_date_for_speech, format_time_for_speech
from utils.text_utils import title_case
from datetime import date


# ─────────────────────────────────────────────────────────────────────────────
# ORDER STATUS ENQUIRY
# ─────────────────────────────────────────────────────────────────────────────

def get_patient_orders(patient_id: int) -> dict:
    """
    Fetch all orders for a verified patient.
    Returns plain-language status descriptions.
    order_id is never included in output.
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                product_name,
                order_status,
                notes,
                placed_at,
                updated_at
            FROM patient_orders
            WHERE patient_id = %s
            ORDER BY placed_at DESC
        """, (patient_id,))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if not rows:
            return {
                "status": "NO_ORDERS",
                "orders": [],
                "count":  0
            }

        orders = []
        for row in rows:
            product = row[0] or "item"
            status  = row[1] or "placed"
            orders.append({
                "product_name":      title_case(product),
                "order_status":      status,
                "status_text":       _order_status_to_speech(status, product),
                "notes":             row[2],
                "placed_at":         str(row[3]),
                "updated_at":        str(row[4])
            })

        return {
            "status": "SUCCESS",
            "orders": orders,
            "count":  len(orders)
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


def _order_status_to_speech(status: str, product: str) -> str:
    """Convert DB order status to plain language for the patient."""
    product_cap = title_case(product)
    status_map = {
        "placed": (
            f"Your {product_cap} order has been placed and is currently "
            f"being prepared. We'll contact you as soon as it's ready."
        ),
        "ready": (
            f"Great news! Your {product_cap} is ready for collection. "
            f"Please visit us during our business hours, "
            f"Monday to Friday, 9 AM to 6 PM."
        ),
        "delivered": (
            f"Our records show that your {product_cap} has already been "
            f"collected. If you have any concerns, please let us know."
        )
    }
    return status_map.get(
        status.lower(),
        f"Your {product_cap} order is currently in progress. "
        f"We'll keep you updated."
    )


# ─────────────────────────────────────────────────────────────────────────────
# UPCOMING APPOINTMENTS
# ─────────────────────────────────────────────────────────────────────────────

def get_upcoming_appointments(patient_id: int) -> dict:
    """
    Fetch upcoming (future, non-cancelled) appointments for a patient.
    appointment_id is never included in output to caller.
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        today_str = date.today().strftime("%d-%m-%Y")

        cursor.execute("""
            SELECT
                preferred_treatment,
                preferred_date,
                preferred_time,
                preferred_dentist,
                status
            FROM appointments
            WHERE patient_id = %s
              AND status NOT IN ('cancelled')
            ORDER BY preferred_date ASC, preferred_time ASC
        """, (patient_id,))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        upcoming = []
        for row in rows:
            d = parse_date(str(row[1]))
            t = parse_time(str(row[2]))

            # Only include future appointments
            if d and d >= date.today():
                upcoming.append({
                    "treatment": row[0],
                    "date":      format_date_for_speech(d) if d else str(row[1]),
                    "time":      format_time_for_speech(t) if t else str(row[2]),
                    "dentist":   row[3],
                    "status":    row[4]
                })

        if not upcoming:
            return {
                "status":       "NO_UPCOMING",
                "appointments": [],
                "count":        0
            }

        return {
            "status":       "SUCCESS",
            "appointments": upcoming,
            "count":        len(upcoming)
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# PAST APPOINTMENTS / TREATMENT HISTORY
# ─────────────────────────────────────────────────────────────────────────────

def get_past_appointments(patient_id: int) -> dict:
    """
    Fetch completed/past appointments for a patient.
    appointment_id is never included in output to caller.
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                preferred_treatment,
                preferred_date,
                preferred_time,
                preferred_dentist,
                status
            FROM appointments
            WHERE patient_id = %s
            ORDER BY preferred_date DESC
        """, (patient_id,))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        past = []
        for row in rows:
            d = parse_date(str(row[1]))

            # Only include past appointments
            if d and d < date.today():
                t = parse_time(str(row[2]))
                past.append({
                    "treatment": row[0],
                    "date":      format_date_for_speech(d),
                    "time":      format_time_for_speech(t) if t else str(row[2]),
                    "dentist":   row[3],
                    "status":    row[4]
                })

        if not past:
            return {
                "status":       "NO_HISTORY",
                "appointments": [],
                "count":        0
            }

        return {
            "status":       "SUCCESS",
            "appointments": past,
            "count":        len(past)
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}
