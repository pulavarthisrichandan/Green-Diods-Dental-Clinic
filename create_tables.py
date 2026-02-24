# """
# create_tables.py — DentalBot v2
# Run once to create all required tables in the database.

# Usage:
#     python create_tables.py
# """

# from db.db_connection import get_db_connection
# from dotenv import load_dotenv

# load_dotenv()


# def create_tables():
#     conn   = get_db_connection()
#     cursor = conn.cursor()

#     print("="*60)
#     print("  DentalBot v2 — Creating Database Tables")
#     print("="*60)

#     tables = {

#         # ── PATIENTS ──────────────────────────────────────────────
#         "patients": """
#             CREATE TABLE IF NOT EXISTS patients (
#                 patient_id      SERIAL PRIMARY KEY,
#                 first_name      VARCHAR(100) NOT NULL,
#                 last_name       VARCHAR(100) NOT NULL,
#                 date_of_birth   VARCHAR(20)  NOT NULL,
#                 contact_number  VARCHAR(20)  NOT NULL,
#                 insurance_info  VARCHAR(200),
#                 created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
#             )
#         """,

#         # ── APPOINTMENTS ──────────────────────────────────────────
#         "appointments": """
#             CREATE TABLE IF NOT EXISTS appointments (
#                 appointment_id      SERIAL PRIMARY KEY,
#                 patient_id          INTEGER REFERENCES patients(patient_id)
#                                     ON DELETE CASCADE,
#                 first_name          VARCHAR(100),
#                 last_name           VARCHAR(100),
#                 date_of_birth       VARCHAR(20),
#                 contact_number      VARCHAR(20),
#                 preferred_treatment VARCHAR(200) NOT NULL,
#                 preferred_date      VARCHAR(50)  NOT NULL,
#                 preferred_time      VARCHAR(50)  NOT NULL,
#                 preferred_dentist   VARCHAR(200) NOT NULL,
#                 status              VARCHAR(50)  DEFAULT 'confirmed',
#                 created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
#             )
#         """,

#         # ── COMPLAINTS ────────────────────────────────────────────
#         "complaints": """
#             CREATE TABLE IF NOT EXISTS complaints (
#                 complaint_id        SERIAL PRIMARY KEY,
#                 complaint_category  VARCHAR(50)  DEFAULT 'general',
#                 patient_name        VARCHAR(200) NOT NULL,
#                 contact_number      VARCHAR(20),
#                 complaint_text      TEXT         NOT NULL,
#                 treatment_name      VARCHAR(200),
#                 dentist_name        VARCHAR(200),
#                 treatment_date      VARCHAR(50),
#                 status              VARCHAR(50)  DEFAULT 'pending',
#                 created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
#             )
#         """,

#         # ── PATIENT ORDERS ────────────────────────────────────────
#         "patient_orders": """
#             CREATE TABLE IF NOT EXISTS patient_orders (
#                 order_id        SERIAL PRIMARY KEY,
#                 patient_id      INTEGER REFERENCES patients(patient_id)
#                                 ON DELETE CASCADE,
#                 product_name    VARCHAR(200) NOT NULL,
#                 order_status    VARCHAR(50)  DEFAULT 'placed',
#                 notes           TEXT,
#                 placed_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
#                 updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
#             )
#         """,

#         # ── BUSINESS LOGS ─────────────────────────────────────────
#         "business_logs": """
#             CREATE TABLE IF NOT EXISTS business_logs (
#                 log_id          SERIAL PRIMARY KEY,
#                 caller_name     VARCHAR(150),
#                 company_name    VARCHAR(200),
#                 contact_number  VARCHAR(20),
#                 purpose         VARCHAR(100),
#                 full_call_notes TEXT,
#                 created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
#             )
#         """
#     }

#     # ── Create each table ─────────────────────────────────────────
#     all_ok = True
#     for table_name, ddl in tables.items():
#         try:
#             cursor.execute(ddl)
#             conn.commit()
#             print(f"  ✅ {table_name}")
#         except Exception as e:
#             conn.rollback()
#             print(f"  ❌ {table_name} — ERROR: {e}")
#             all_ok = False

#     # ── Verify all tables exist ───────────────────────────────────
#     print("\n" + "-"*60)
#     print("  Verifying tables...")
#     print("-"*60)

#     for table_name in tables.keys():
#         try:
#             cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
#             count = cursor.fetchone()[0]
#             print(f"  ✅ {table_name:<20} — {count} records")
#         except Exception as e:
#             conn.rollback()
#             print(f"  ❌ {table_name:<20} — NOT FOUND: {e}")
#             all_ok = False

#     cursor.close()
#     conn.close()

#     print("\n" + "="*60)
#     if all_ok:
#         print("  ✅ All tables created and verified successfully!")
#         print("  You can now run: python check_db.py")
#     else:
#         print("  ⚠️  Some tables had errors. Check output above.")
#     print("="*60)


# if __name__ == "__main__":
#     create_tables()
"""
reset_db.py — DentalBot v2
Completely wipes all data and recreates tables fresh.

Usage:
    python reset_db.py
"""

from db.db_connection import db_cursor
from dotenv import load_dotenv

load_dotenv()


def reset():
    conn   = db_cursor()
    cursor = conn.cursor()

    print("=" * 60)
    print("  DentalBot v2 — Full Database Reset")
    print("=" * 60)

    # ── STEP 1: Drop everything ───────────────────────────────────
    print("\n[STEP 1] Dropping all existing tables...")

    drop_order = [
        "appointments_backup",
        "complaints_backup",
        "business_logs_backup",
        "patients_backup",
        "business_logs",
        "complaints",
        "patient_orders",
        "appointments",
        "patients"
    ]

    for table in drop_order:
        try:
            cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            conn.commit()
            print(f"  ✅ Dropped: {table}")
        except Exception as e:
            conn.rollback()
            print(f"  ⚠️  {table} — {e}")


    # ── STEP 2: Create fresh tables ───────────────────────────────
    print("\n[STEP 2] Creating fresh tables...")

    tables = [

        ("patients", """
            CREATE TABLE patients (
                patient_id      SERIAL PRIMARY KEY,
                first_name      VARCHAR(100) NOT NULL,
                last_name       VARCHAR(100) NOT NULL,
                date_of_birth   VARCHAR(20)  NOT NULL,
                contact_number  VARCHAR(20)  NOT NULL,
                insurance_info  VARCHAR(200),
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),

        ("appointments", """
            CREATE TABLE appointments (
                appointment_id      SERIAL PRIMARY KEY,
                patient_id          INTEGER REFERENCES patients(patient_id)
                                    ON DELETE CASCADE,
                first_name          VARCHAR(100),
                last_name           VARCHAR(100),
                date_of_birth       VARCHAR(20),
                contact_number      VARCHAR(20),
                preferred_treatment VARCHAR(200) NOT NULL,
                preferred_date      VARCHAR(50)  NOT NULL,
                preferred_time      VARCHAR(50)  NOT NULL,
                preferred_dentist   VARCHAR(200) NOT NULL,
                status              VARCHAR(50)  DEFAULT 'confirmed',
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),

        ("complaints", """
            CREATE TABLE complaints (
                complaint_id        SERIAL PRIMARY KEY,
                complaint_category  VARCHAR(50)  DEFAULT 'general',
                patient_name        VARCHAR(200) NOT NULL,
                contact_number      VARCHAR(20),
                complaint_text      TEXT         NOT NULL,
                treatment_name      VARCHAR(200),
                dentist_name        VARCHAR(200),
                treatment_date      VARCHAR(50),
                status              VARCHAR(50)  DEFAULT 'pending',
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),

        ("patient_orders", """
            CREATE TABLE patient_orders (
                order_id        SERIAL PRIMARY KEY,
                patient_id      INTEGER REFERENCES patients(patient_id)
                                ON DELETE CASCADE,
                product_name    VARCHAR(200) NOT NULL,
                order_status    VARCHAR(50)  DEFAULT 'placed',
                notes           TEXT,
                placed_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),

        ("business_logs", """
            CREATE TABLE business_logs (
                log_id          SERIAL PRIMARY KEY,
                caller_name     VARCHAR(150),
                company_name    VARCHAR(200),
                contact_number  VARCHAR(20),
                purpose         VARCHAR(100),
                full_call_notes TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    ]

    for table_name, ddl in tables:
        try:
            cursor.execute(ddl)
            conn.commit()
            print(f"  ✅ Created: {table_name}")
        except Exception as e:
            conn.rollback()
            print(f"  ❌ {table_name} FAILED — {e}")


    # ── STEP 3: Verify ────────────────────────────────────────────
    print("\n[STEP 3] Verifying...")
    print("-" * 60)

    for table_name, _ in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            count = cursor.fetchone()[0]
            print(f"  ✅ {table_name:<25} — {count} records (empty)")
        except Exception as e:
            conn.rollback()
            print(f"  ❌ {table_name:<25} — MISSING: {e}")

    cursor.close()
    conn.close()

    print("\n" + "=" * 60)
    print("  ✅ Database reset complete — all tables are fresh!")
    print("  Run: python check_db.py to confirm")
    print("=" * 60)


if __name__ == "__main__":
    print("\n⚠️  WARNING: This will DELETE ALL DATA permanently.")
    print("   There is no undo.")
    confirm = input("\n   Type 'delete everything' to confirm: ")

    if confirm.strip().lower() == "delete everything":
        reset()
    else:
        print("\n   Reset cancelled. No changes made.")
