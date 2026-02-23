"""
check_db.py — DentalBot v2
Quick database inspector — run anytime to check all tables.

Usage:
    python check_db.py            → shows all tables summary
    python check_db.py patients   → shows patients table
    python check_db.py appts      → shows appointments
    python check_db.py complaints → shows complaints
    python check_db.py orders     → shows orders
    python check_db.py business   → shows business_logs
    python check_db.py clear      → clears all test data (keeps schema)
"""

import sys
from db.db_connection import get_db_connection
from dotenv import load_dotenv

load_dotenv()


def separator(title=""):
    width = 80
    if title:
        print(f"\n{'='*width}")
        print(f"  {title}")
        print(f"{'='*width}")
    else:
        print("-" * width)


def show_patients():
    separator("PATIENTS")
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT patient_id, first_name, last_name,
               date_of_birth, contact_number, insurance_info, created_at
        FROM patients
        ORDER BY created_at DESC
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        print("  No patients found.")
        return

    print(f"  {'ID':<6} {'Name':<25} {'DOB':<15} {'Contact':<15} {'Insurance':<15} {'Created'}")
    separator()
    for r in rows:
        name = f"{r[1]} {r[2]}"
        ins  = r[5] or "—"
        print(f"  {r[0]:<6} {name:<25} {str(r[3]):<15} {r[4]:<15} {ins:<15} {str(r[6])[:16]}")

    print(f"\n  Total: {len(rows)} patients")


def show_appointments():
    separator("APPOINTMENTS")
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            a.appointment_id,
            p.first_name || ' ' || p.last_name AS patient_name,
            a.preferred_treatment,
            a.preferred_date,
            a.preferred_time,
            a.preferred_dentist,
            a.status,
            a.created_at
        FROM appointments a
        JOIN patients p ON a.patient_id = p.patient_id
        ORDER BY a.created_at DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        print("  No appointments found.")
        return

    print(f"  {'ID':<6} {'Patient':<22} {'Treatment':<30} {'Date':<12} {'Time':<8} {'Dentist':<20} {'Status'}")
    separator()
    for r in rows:
        print(
            f"  {r[0]:<6} {r[1]:<22} {r[2]:<30} "
            f"{str(r[3]):<12} {str(r[4]):<8} {r[5]:<20} {r[6]}"
        )

    print(f"\n  Total: {len(rows)} appointments")


def show_complaints():
    separator("COMPLAINTS")
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT complaint_id, complaint_category, patient_name,
               contact_number, LEFT(complaint_text, 60),
               treatment_name, dentist_name, status, created_at
        FROM complaints
        ORDER BY created_at DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        print("  No complaints found.")
        return

    for r in rows:
        print(f"\n  ID       : {r[0]}")
        print(f"  Category : {r[1]}")
        print(f"  Patient  : {r[2]} ({r[3]})")
        print(f"  Text     : {r[4]}...")
        if r[5]: print(f"  Treatment: {r[5]}")
        if r[6]: print(f"  Dentist  : {r[6]}")
        print(f"  Status   : {r[7]}")
        print(f"  Date     : {str(r[8])[:16]}")
        separator()

    print(f"  Total: {len(rows)} complaints")


def show_orders():
    separator("PATIENT ORDERS")
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            po.order_id,
            p.first_name || ' ' || p.last_name AS patient_name,
            po.product_name,
            po.order_status,
            po.notes,
            po.placed_at,
            po.updated_at
        FROM patient_orders po
        JOIN patients p ON po.patient_id = p.patient_id
        ORDER BY po.placed_at DESC
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        print("  No orders found.")
        return

    print(f"  {'ID':<6} {'Patient':<22} {'Product':<25} {'Status':<12} {'Notes':<30} {'Placed'}")
    separator()
    for r in rows:
        notes = (r[4] or "—")[:28]
        print(
            f"  {r[0]:<6} {r[1]:<22} {r[2]:<25} "
            f"{r[3]:<12} {notes:<30} {str(r[5])[:10]}"
        )

    print(f"\n  Total: {len(rows)} orders")


def show_business_logs():
    separator("BUSINESS CALL LOGS")
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT log_id, caller_name, company_name,
            contact_number, purpose, logged_at
        FROM business_logs
        ORDER BY logged_at DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        print("  No business logs found.")
        return

    print(f"  {'ID':<6} {'Caller':<20} {'Company':<22} {'Contact':<15} {'Purpose':<25} {'Date'}")
    separator()
    for r in rows:
        caller  = (r[1] or "—")[:18]
        company = (r[2] or "—")[:20]
        contact = (r[3] or "—")[:13]
        purpose = (r[4] or "—")[:23]
        print(
            f"  {r[0]:<6} {caller:<20} {company:<22} "
            f"{contact:<15} {purpose:<25} {str(r[5])[:16]}"
        )

    print(f"\n  Total: {len(rows)} logs")


def show_summary():
    separator("DATABASE SUMMARY — DentalBot v2")

    tables = [
        ("patients",       "Patients"),
        ("appointments",   "Appointments"),
        ("complaints",     "Complaints"),
        ("patient_orders", "Patient Orders"),
        ("business_logs",  "Business Call Logs")
    ]

    for table, label in tables:
        # Fresh connection per table — no transaction bleed
        try:
            conn   = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  {label:<25} : {count} records")
            cursor.close()
            conn.close()
        except Exception as e:
            conn.rollback()   # ← clear failed transaction
            print(f"  {label:<25} : TABLE MISSING — run schema.sql to create it")
            cursor.close()
            conn.close()

    # Today's appointments — separate connection
    try:
        from datetime import date
        today  = date.today().strftime("%Y-%m-%d")
        conn   = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM appointments "
            "WHERE preferred_date = %s AND status != 'cancelled'",
            (today,)
        )
        today_count = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM complaints WHERE status = 'pending'"
        )
        pending = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM patient_orders WHERE order_status = 'ready'"
        )
        ready = cursor.fetchone()[0]

        print(f"\n  Today's appointments ({today}): {today_count}")
        print(f"  Pending complaints            : {pending}")
        print(f"  Orders ready for collection   : {ready}")

        cursor.close()
        conn.close()

    except Exception as e:
        conn.rollback()
        print(f"\n  Could not fetch summary stats: {e}")
        cursor.close()
        conn.close()

    separator()



def clear_test_data():
    separator("CLEAR TEST DATA")
    confirm = input("  ⚠️  This will DELETE all data. Type 'yes' to confirm: ")
    if confirm.strip().lower() != "yes":
        print("  Cancelled.")
        return

    conn   = get_db_connection()
    cursor = conn.cursor()

    tables = [
        "business_logs",
        "patient_orders",
        "complaints",
        "appointments",
        "patients"
    ]

    for table in tables:
        cursor.execute(f"DELETE FROM {table}")
        print(f"  ✅ Cleared: {table}")

    conn.commit()
    cursor.close()
    conn.close()
    print("\n  All test data cleared. Schema preserved.")
    separator()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"

    commands = {
        "patients":   show_patients,
        "appts":      show_appointments,
        "complaints": show_complaints,
        "orders":     show_orders,
        "business":   show_business_logs,
        "clear":      clear_test_data,
        "all":        lambda: (
            show_summary(),
            show_patients(),
            show_appointments(),
            show_complaints(),
            show_orders(),
            show_business_logs()
        )
    }

    fn = commands.get(arg)
    if fn:
        fn()
    else:
        print(f"\n  Unknown command: '{arg}'")
        print("  Available: patients | appts | complaints | orders | business | clear | all")
