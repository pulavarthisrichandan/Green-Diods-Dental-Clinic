"""
Business Executor - DentalBot v2

DB operations for:
    - Logging supplier/agent/business calls  → business_logs table
    - Updating patient order status          → patient_orders table
"""

from db.db_connection import db_cursor
from utils.phone_utils import normalize_phone
from utils.text_utils import title_case


# ─────────────────────────────────────────────────────────────────────────────
# LOG BUSINESS CALL
# ─────────────────────────────────────────────────────────────────────────────

def log_business_call(caller_name, company_name, contact_number, purpose, full_notes=None):
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            INSERT INTO business_logs
            (caller_name, company_name, contact_number, purpose, full_notes)
            VALUES (%s,%s,%s,%s,%s)
        """, (caller_name, company_name, contact_number, purpose, full_notes))


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE ORDER STATUS — called when supplier says "order is ready"
# ─────────────────────────────────────────────────────────────────────────────

def update_order_status_by_patient_name(patient_name, product_name, new_status, notes=None):
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            UPDATE patient_orders
            SET order_status = %s, notes = %s, updated_at = NOW()
            WHERE product_name = %s
              AND patient_id = (
                  SELECT patient_id FROM patients
                  WHERE first_name || ' ' || last_name = %s
              )
        """, (new_status, notes, product_name, patient_name))


# ─────────────────────────────────────────────────────────────────────────────
# FETCH ALL PENDING ORDERS (management portal use)
# ─────────────────────────────────────────────────────────────────────────────

def get_all_pending_orders() -> dict:
    """
    Internal use only — management portal.
    Returns all orders with status 'placed' or 'ready'.
    """
    try:
        with db_cursor() as (cursor, conn):

            cursor.execute("""
                SELECT
                    order_id,
                    patient_id,
                    first_name,
                    last_name,
                    contact_number,
                    product_name,
                    order_status,
                    notes,
                    placed_at,
                    updated_at
                FROM patient_orders
                WHERE order_status IN ('placed', 'ready')
                ORDER BY placed_at DESC
            """)

            rows = cursor.fetchall()

        orders = []
        for row in rows:
            orders.append({
                "order_id":       row[0],
                "patient_id":     row[1],
                "first_name":     row[2],
                "last_name":      row[3],
                "contact_number": row[4],
                "product_name":   row[5],
                "order_status":   row[6],
                "notes":          row[7],
                "placed_at":      str(row[8]),
                "updated_at":     str(row[9])
            })

        return {
            "status": "SUCCESS",
            "orders": orders,
            "count":  len(orders)
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# FETCH ORDER STATUS FOR PATIENT (general_enquiry module use)
# ─────────────────────────────────────────────────────────────────────────────

def get_orders_for_patient(patient_id: int) -> dict:
    """
    Fetch all orders for a verified patient.
    Called by general_enquiry module when patient asks about their order.
    """
    try:
        with db_cursor() as (cursor, conn):

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

        orders = []
        for row in rows:
            orders.append({
                "product_name": row[0],
                "order_status": row[1],
                "notes":        row[2],
                "placed_at":    str(row[3]),
                "updated_at":   str(row[4])
            })

        return {
            "status": "SUCCESS",
            "orders": orders,
            "count":  len(orders)
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}
