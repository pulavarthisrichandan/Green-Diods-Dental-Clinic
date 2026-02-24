"""
Business Executor - DentalBot v2

DB operations for:
    - Logging supplier/agent/business calls  → business_logs table
    - Updating patient order status          → patient_orders table
"""

from db.db_connection import get_db_connection, db_cursor
from utils.phone_utils import normalize_phone
from utils.text_utils import title_case


# ─────────────────────────────────────────────────────────────────────────────
# LOG BUSINESS CALL
# ─────────────────────────────────────────────────────────────────────────────

def log_business_call(
    caller_name:    str  = None,
    company_name:   str  = None,
    contact_number: str  = None,
    purpose:        str  = None,
    full_notes:     str  = None
) -> dict:
    """
    Log a supplier/agent/business call to business_logs table.

    Returns:
        status = LOGGED  → success
        status = ERROR   → DB error
    """
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO business_logs (
                caller_name,
                company_name,
                contact_number,
                purpose,
                full_call_notes
            ) VALUES (%s, %s, %s, %s, %s)
            RETURNING log_id
        """, (
            title_case(caller_name)   if caller_name    else None,
            title_case(company_name)  if company_name   else None,
            normalize_phone(contact_number) if contact_number else None,
            purpose,
            full_notes
        ))

        _ = cursor.fetchone()[0]    # log_id — internal only
        conn.commit()
        cursor.close()
        conn.close()

        return {"status": "LOGGED"}

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE ORDER STATUS — called when supplier says "order is ready"
# ─────────────────────────────────────────────────────────────────────────────

def update_order_status_by_patient_name(
    patient_name: str,
    product_name: str,
    new_status:   str  = "ready",
    notes:        str  = None
) -> dict:
    """
    Update patient_orders.order_status when a supplier calls to say
    a patient's item is ready.

    Looks up by patient last name + product name (fuzzy match).
    order_id is INTERNAL — never shown to user.

    Returns:
        status = UPDATED      → record found and updated
        status = NOT_FOUND    → no matching order found
        status = ERROR        → DB error
    """
    if not patient_name or not product_name:
        return {
            "status":  "MISSING_INFO",
            "message": "Patient name and product name are required."
        }

    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        # Try to match on patient name (first + last or last name)
        name_parts = patient_name.strip().split()
        last_name  = name_parts[-1] if name_parts else patient_name

        cursor.execute("""
            UPDATE patient_orders
            SET    order_status = %s,
                   notes        = COALESCE(%s, notes),
                   updated_at   = CURRENT_TIMESTAMP
            WHERE  (
                LOWER(last_name)   LIKE LOWER(%s)
                OR
                LOWER(first_name || ' ' || last_name) LIKE LOWER(%s)
            )
            AND LOWER(product_name) LIKE LOWER(%s)
            AND order_status != 'delivered'
            RETURNING order_id, first_name, last_name, product_name
        """, (
            new_status,
            notes,
            f"%{last_name}%",
            f"%{patient_name}%",
            f"%{product_name.split()[0]}%"   # match on first word of product
        ))

        row = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        if row:
            return {
                "status":       "UPDATED",
                "patient_name": f"{row[1]} {row[2]}",
                "product_name": row[3],
                "new_status":   new_status
            }

        return {
            "status":  "NOT_FOUND",
            "message": (
                f"No pending order found for '{patient_name}' "
                f"with product '{product_name}'."
            )
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


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
