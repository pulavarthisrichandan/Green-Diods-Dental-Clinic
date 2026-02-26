"""
business/business_executor.py  --  DentalBot v2
Handles business/supplier call logging and order status updates.

Supplier flow (Type 3):
  1. Caller says "I'm from [company]"
  2. Bot calls check_supplier(company_name) to verify they're in our DB
  3. If valid: bot asks for patient_id (or last name+DOB) and product name
  4. Bot calls update_order_by_patient_id(patient_id, product_name)
  5. Bot confirms update to caller
"""

from db.db_connection import db_cursor
from utils.phone_utils import normalize_phone
from utils.text_utils import title_case
import traceback


# ── Known suppliers (seeded once via create_tables.py) ───────────────────────
KNOWN_SUPPLIERS = [
    {
        "supplier_id":   1,
        "company_name":  "AusDental Labs Pty Ltd",
        "specialty":     "Crowns, Bridges, Veneers, Tooth Caps",
        "contact":       "03 9100 2211",
        "email":         "orders@ausdentalabs.com.au",
    },
    {
        "supplier_id":   2,
        "company_name":  "MedPro Orthodontics",
        "specialty":     "Braces, Clear Aligners, Retainers",
        "contact":       "03 9200 4455",
        "email":         "supply@medproortho.com.au",
    },
    {
        "supplier_id":   3,
        "company_name":  "Southern Implant Supply Co.",
        "specialty":     "Dental Implants, Abutments, Implant Crowns",
        "contact":       "03 9300 6677",
        "email":         "logistics@southernimplant.com.au",
    },
    {
        "supplier_id":   4,
        "company_name":  "PrecisionDenture Works",
        "specialty":     "Dentures, Partial Plates, Immediate Dentures",
        "contact":       "03 9400 8899",
        "email":         "production@precisiondenture.com.au",
    },
    {
        "supplier_id":   5,
        "company_name":  "OralCraft Technologies",
        "specialty":     "Custom Mouthguards, Night Guards, Sports Guards",
        "contact":       "03 9500 1122",
        "email":         "dispatch@oralcraft.com.au",
    },
]


def check_supplier(company_name: str) -> dict:
    """
    Check if the calling company is a known/authorised supplier.
    Returns the supplier record if found, or NOT_FOUND.
    Uses case-insensitive partial match so 'ausdental' matches 'AusDental Labs Pty Ltd'.
    """
    if not company_name:
        return {"status": "NOT_FOUND", "message": "No company name provided."}
    name_lower = company_name.lower().strip()
    for s in KNOWN_SUPPLIERS:
        if name_lower in s["company_name"].lower() or s["company_name"].lower() in name_lower:
            return {"status": "FOUND", "supplier": s}
    return {
        "status": "NOT_FOUND",
        "message": (
            f"I'm sorry, I don't have '{company_name}' in our authorised supplier list. "
            "I'll pass your details to our management team."
        ),
    }


def get_all_suppliers() -> dict:
    """Return the full list of known suppliers (for bot reference)."""
    return {"status": "SUCCESS", "suppliers": KNOWN_SUPPLIERS, "count": len(KNOWN_SUPPLIERS)}


# ── Business call logging ─────────────────────────────────────────────────────

def log_business_call(
    caller_name: str = None,
    company_name: str = None,
    contact_number: str = None,
    purpose: str = None,
    full_notes: str = None,
) -> dict:
    try:
        with db_cursor() as (cursor, conn):
            cursor.execute(
                """
                INSERT INTO business_logs
                    (caller_name, company_name, contact_number, purpose, full_call_notes)
                VALUES (%s, %s, %s, %s, %s) RETURNING log_id
                """,
                (
                    title_case(caller_name) if caller_name else None,
                    title_case(company_name) if company_name else None,
                    normalize_phone(contact_number) if contact_number else None,
                    purpose,
                    full_notes,
                ),
            )
            conn.commit()
        return {"status": "LOGGED"}
    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


# ── Order status updates ──────────────────────────────────────────────────────

def update_order_by_patient_id(
    patient_id: int,
    product_name: str,
    new_status: str = "ready",
    notes: str = None,
) -> dict:
    """
    Primary supplier order-ready update — uses patient_id for exact match.
    Called when a verified supplier says "order for patient ID X is ready."
    """
    if not patient_id or not product_name:
        return {"status": "MISSING_INFO", "message": "patient_id and product_name are required."}
    try:
        with db_cursor() as (cursor, conn):
            cursor.execute(
                """
                UPDATE patient_orders
                SET    order_status = %s,
                       notes        = COALESCE(%s, notes),
                       updated_at   = CURRENT_TIMESTAMP
                WHERE  patient_id   = %s
                  AND  LOWER(product_name) LIKE LOWER(%s)
                  AND  order_status != 'delivered'
                RETURNING order_id, first_name, last_name, product_name
                """,
                (new_status, notes, patient_id, f"%{product_name.split()[0]}%"),
            )
            row = cursor.fetchone()
            conn.commit()
        if row:
            return {
                "status":      "UPDATED",
                "order_id":    row[0],
                "patient_name": f"{row[1]} {row[2]}",
                "product_name": row[3],
                "new_status":   new_status,
            }
        return {
            "status":  "NOT_FOUND",
            "message": f"No pending order found for patient_id={patient_id} with product '{product_name}'.",
        }
    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


def update_order_status_by_patient_name(
    patient_name: str,
    product_name: str,
    new_status: str = "ready",
    notes: str = None,
) -> dict:
    """Fallback: fuzzy match on last name when patient_id is unavailable."""
    if not patient_name or not product_name:
        return {"status": "MISSING_INFO", "message": "Patient name and product name are required."}
    try:
        name_parts = patient_name.strip().split()
        last_name  = name_parts[-1] if name_parts else patient_name
        with db_cursor() as (cursor, conn):
            cursor.execute(
                """
                UPDATE patient_orders
                SET    order_status = %s,
                       notes        = COALESCE(%s, notes),
                       updated_at   = CURRENT_TIMESTAMP
                WHERE  (LOWER(last_name)  LIKE LOWER(%s)
                     OR LOWER(first_name || ' ' || last_name) LIKE LOWER(%s))
                  AND  LOWER(product_name) LIKE LOWER(%s)
                  AND  order_status != 'delivered'
                RETURNING order_id, first_name, last_name, product_name
                """,
                (new_status, notes, f"%{last_name}%", f"%{patient_name}%",
                 f"%{product_name.split()[0]}%"),
            )
            row = cursor.fetchone()
            conn.commit()
        if row:
            return {
                "status":       "UPDATED",
                "patient_name": f"{row[1]} {row[2]}",
                "product_name": row[3],
                "new_status":   new_status,
            }
        return {
            "status":  "NOT_FOUND",
            "message": f"No pending order found for {patient_name} / {product_name}.",
        }
    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


def get_all_pending_orders() -> dict:
    try:
        with db_cursor() as (cursor, conn):
            cursor.execute(
                """
                SELECT order_id, patient_id, first_name, last_name, contact_number,
                       product_name, order_status, notes, placed_at, updated_at
                FROM   patient_orders
                WHERE  order_status IN ('placed', 'ready')
                ORDER  BY placed_at DESC
                """
            )
            rows = cursor.fetchall()
        return {
            "status": "SUCCESS",
            "orders": [
                {
                    "order_id": r[0], "patient_id": r[1], "first_name": r[2],
                    "last_name": r[3], "contact_number": r[4], "product_name": r[5],
                    "order_status": r[6], "notes": r[7],
                    "placed_at": str(r[8]), "updated_at": str(r[9]),
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}


def get_orders_for_patient(patient_id: int) -> dict:
    try:
        with db_cursor() as (cursor, conn):
            cursor.execute(
                """
                SELECT product_name, order_status, notes, placed_at, updated_at
                FROM   patient_orders
                WHERE  patient_id = %s
                ORDER  BY placed_at DESC
                """,
                (patient_id,),
            )
            rows = cursor.fetchall()
        return {
            "status": "SUCCESS",
            "orders": [
                {
                    "product_name": r[0], "order_status": r[1],
                    "notes": r[2], "placed_at": str(r[3]), "updated_at": str(r[4]),
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception as e:
        traceback.print_exc()
        return {"status": "ERROR", "message": str(e)}