"""
DentalBot v2 — Database Setup
Run once: python -m DB.create_tables
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

import os
import psycopg2

def get_db_connection():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    return psycopg2.connect(
        database_url,
        connect_timeout=5,
        sslmode="require"
    )

def create_tables():
    conn   = get_db_connection()
    cursor = conn.cursor()

    # ── Drop in reverse dependency order ──────────────────────────
    drop_order = [
        "business_logs",
        "complaints",
        "patient_orders",
        "appointment_updates",
        "cancellations",
        "appointments",
        "patients"
    ]
    print("Dropping existing tables...")
    for table in drop_order:
        cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
        print(f"  dropped: {table}")
    conn.commit()

    # ── 1. patients ───────────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE patients (
        patient_id     SERIAL PRIMARY KEY,
        first_name     TEXT NOT NULL,
        last_name      TEXT NOT NULL,
        date_of_birth  TEXT NOT NULL,        -- DD-MM-YYYY
        contact_number TEXT NOT NULL,
        insurance_info TEXT DEFAULT NULL,
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    print("  created: patients")

    # ── 2. appointments ───────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE appointments (
        appointment_id      SERIAL PRIMARY KEY,
        patient_id          INT  REFERENCES patients(patient_id),
        first_name          TEXT NOT NULL,
        last_name           TEXT NOT NULL,
        date_of_birth       TEXT NOT NULL,   -- DD-MM-YYYY
        contact_number      TEXT NOT NULL,
        preferred_treatment TEXT NOT NULL,
        preferred_date      TEXT NOT NULL,   -- DD-MM-YYYY
        preferred_time      TEXT NOT NULL,   -- HH:MM AM/PM
        preferred_dentist   TEXT NOT NULL,
        status              TEXT DEFAULT 'booked',
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    print("  created: appointments")

    # ── 3. appointment_updates (audit log) ────────────────────────
    cursor.execute("""
    CREATE TABLE appointment_updates (
        update_id      SERIAL PRIMARY KEY,
        appointment_id INT  REFERENCES appointments(appointment_id),
        updated_fields JSONB NOT NULL,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    print("  created: appointment_updates")

    # ── 4. cancellations ──────────────────────────────────────────
    cursor.execute("""
    CREATE TABLE cancellations (
        cancellation_id SERIAL PRIMARY KEY,
        appointment_id  INT  REFERENCES appointments(appointment_id),
        reason          TEXT,
        cancelled_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    print("  created: cancellations")

    # ── 5. patient_orders ─────────────────────────────────────────
    # Placed by management portal; updated by supplier calls via bot.
    cursor.execute("""
    CREATE TABLE patient_orders (
        order_id       SERIAL PRIMARY KEY,
        patient_id     INT  REFERENCES patients(patient_id),
        first_name     TEXT,
        last_name      TEXT,
        contact_number TEXT,
        product_name   TEXT NOT NULL,        -- e.g. Dentures, X-Ray, Tooth Cap
        order_status   TEXT DEFAULT 'placed',-- placed | ready | delivered
        notes          TEXT,
        placed_by      TEXT DEFAULT 'management',
        placed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    print("  created: patient_orders")

    # ── 6. complaints (2 categories) ──────────────────────────────
    cursor.execute("""
    CREATE TABLE complaints (
        complaint_id       SERIAL PRIMARY KEY,
        complaint_category TEXT NOT NULL
            CHECK (complaint_category IN ('general', 'treatment')),
        patient_name       TEXT NOT NULL,
        contact_number     TEXT NOT NULL,
        complaint_text     TEXT NOT NULL,
        -- treatment-specific (NULL for general complaints)
        treatment_name     TEXT DEFAULT NULL,
        dentist_name       TEXT DEFAULT NULL,
        treatment_date     TEXT DEFAULT NULL, -- optional, DD-MM-YYYY
        status             TEXT DEFAULT 'pending',
        created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    print("  created: complaints")

    # ── 7. business_logs (supplier / agent calls) ─────────────────
    cursor.execute("""
    CREATE TABLE business_logs (
        log_id          SERIAL PRIMARY KEY,
        caller_name     TEXT,
        company_name    TEXT,
        contact_number  TEXT,
        purpose         TEXT,
        full_call_notes TEXT,
        logged_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    print("  created: business_logs")

    cursor.close()
    conn.close()
    print("\n✅  All tables created successfully.")

if __name__ == "__main__":
    create_tables()

