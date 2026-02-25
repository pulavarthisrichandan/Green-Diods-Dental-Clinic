"""
Business Executor - DentalBot v2
Old logic + new db_cursor() syntax.
"""

from db.db_connection import db_cursor
from utils.phone_utils import normalize_phone
from utils.text_utils import title_case
import traceback


# ─────────────────────────────────────────────────────────────────────────────
# LOG BUSINESS CALL
# ─────────────────────────────────────────────────────────────────────────────

def log_business_call(
    caller_name:    str = None,
    company_name:   str = None,
    contact_number: str = None,
    purpose:        str = None,
    full_notes:     str = None
) -> dict:
    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("""
                INSERT INTO business_logs (
                    caller_name, company_name, contact_number,
                    purpose, full_notes
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING log_id
            """, (
                title_case(caller_name)          if caller_name    else None,  # ✅
                title_case(company_name)         if company_name   else None,  # ✅
                normalize_phone(contact_number)  if contact_number else None,  # ✅
                purpose,
                full_notes
            ))
            _ = cursor.fetchone()[0]   # log_id — internal only

        return {"status": "LOGGED"}

    except Exception as e:
        print("[BUSINESS] ❌ log_business_call failed:")
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE ORDER STATUS (supplier says order is ready)
# ─────────────────────────────────────────────────────────────────────────────

def update_order_status_by_patient_name(
    patient_name: str,
    product_name: str,
    new_status:   str = "ready",
    notes:        str = None
) -> dict:
    if not patient_name or not product_name:
        return {
            "status":  "MISSING_INFO",
            "message": "Patient name and product name are required."
        }

    try:
        # ✅ Fuzzy match on last name or full name — handles "John Smith" or "Smith"
        name_parts = patient_name.strip().split()
        last_name  = name_parts[-1] if name_parts else patient_name

        with db_cursor() as (cursor, conn):
            cursor.execute("""
                UPDATE patient_orders
                SET    order_status = %s,
                       notes        = COALESCE(%s, notes),
                       updated_at   = CURRENT_TIMESTAMP
                WHERE  (
                    LOWER(last_name)                      LIKE LOWER(%s)
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
                f"%{product_name.split()[0]}%"   # ✅ match on first keyword of product
            ))
            row = cursor.fetchone()

        if row:
            return {
                "status":       "UPDATED",
                "patient_name": f"{row[1]} {row[2]}",
                "product_name": row[3],
                "new_status":   new_status
            }

        return {
            "status":  "NOT_FOUND",
            "message": f"No pending order found for '{patient_name}' with product '{product_name}'."
        }

    except Exception as e:
        print("[BUSINESS] ❌ update_order_status_by_patient_name failed:")
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# GET ALL PENDING ORDERS (management portal only)
# ─────────────────────────────────────────────────────────────────────────────

def get_all_pending_orders() -> dict:
    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("""
                SELECT order_id, patient_id, first_name, last_name,
                       contact_number, product_name, order_status,
                       notes, placed_at, updated_at
                FROM patient_orders
                WHERE order_status IN ('placed', 'ready')
                ORDER BY placed_at DESC
            """)
            rows = cursor.fetchall()

        return {
            "status": "SUCCESS",
            "orders": [
                {
                    "order_id":       r[0],
                    "patient_id":     r[1],
                    "first_name":     r[2],
                    "last_name":      r[3],
                    "contact_number": r[4],
                    "product_name":   r[5],
                    "order_status":   r[6],
                    "notes":          r[7],
                    "placed_at":      str(r[8]),
                    "updated_at":     str(r[9])
                } for r in rows
            ],
            "count": len(rows)
        }

    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# GET ORDERS FOR PATIENT (general enquiry use)
# ─────────────────────────────────────────────────────────────────────────────

def get_orders_for_patient(patient_id: int) -> dict:
    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("""
                SELECT product_name, order_status, notes, placed_at, updated_at
                FROM patient_orders
                WHERE patient_id = %s
                ORDER BY placed_at DESC
            """, (patient_id,))
            rows = cursor.fetchall()

        return {
            "status": "SUCCESS",
            "orders": [
                {
                    "product_name": r[0],
                    "order_status": r[1],
                    "notes":        r[2],
                    "placed_at":    str(r[3]),
                    "updated_at":   str(r[4])
                } for r in rows
            ],
            "count": len(rows)
        }

    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}
