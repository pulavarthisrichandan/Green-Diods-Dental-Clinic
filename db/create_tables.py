"""
DB/create_tables.py  --  DentalBot v2
Run once:  python -m DB.create_tables
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()


def db_cursor():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg2.connect(database_url, connect_timeout=5, sslmode="require")


def create_tables():
    conn   = db_cursor()
    cursor = conn.cursor()

    # ── Drop in dependency order ──────────────────────────────────────────────
    drop_order = [
        "business_logs", "complaints", "patient_orders",
        "appointment_updates", "cancellations", "appointments",
        "suppliers", "patients",
    ]
    print("Dropping existing tables...")
    for table in drop_order:
        cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        print(f"  dropped {table}")
    conn.commit()

    # ── 1. patients ───────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE patients (
            patient_id     SERIAL PRIMARY KEY,
            first_name     TEXT NOT NULL,
            last_name      TEXT NOT NULL,
            date_of_birth  TEXT NOT NULL,         -- DD-MON-YYYY  e.g. 15 Jun 1990
            contact_number TEXT NOT NULL,
            insurance_info TEXT DEFAULT NULL,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("created patients")

    # ── 2. appointments ───────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE appointments (
            appointment_id      SERIAL PRIMARY KEY,
            patient_id          INT REFERENCES patients(patient_id),
            first_name          TEXT NOT NULL,
            last_name           TEXT NOT NULL,
            date_of_birth       TEXT NOT NULL,
            contact_number      TEXT NOT NULL,
            preferred_treatment TEXT NOT NULL,
            preferred_date      TEXT NOT NULL,    -- YYYY-MM-DD
            preferred_time      TEXT NOT NULL,    -- HH:MM
            preferred_dentist   TEXT NOT NULL,
            status              TEXT DEFAULT 'confirmed',
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("created appointments")

    # ── 3. appointment_updates (audit log) ────────────────────────────────────
    cursor.execute("""
        CREATE TABLE appointment_updates (
            update_id      SERIAL PRIMARY KEY,
            appointment_id INT REFERENCES appointments(appointment_id),
            updated_fields JSONB NOT NULL,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("created appointment_updates")

    # ── 4. cancellations ──────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE cancellations (
            cancellation_id SERIAL PRIMARY KEY,
            appointment_id  INT REFERENCES appointments(appointment_id),
            reason          TEXT,
            cancelled_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("created cancellations")

    # ── 5. patient_orders ─────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE patient_orders (
            order_id       SERIAL PRIMARY KEY,
            patient_id     INT REFERENCES patients(patient_id),
            first_name     TEXT,
            last_name      TEXT,
            contact_number TEXT,
            product_name   TEXT NOT NULL,   -- e.g. Dentures, Tooth Cap, Braces
            order_status   TEXT DEFAULT 'placed'
                           CHECK (order_status IN ('placed', 'ready', 'delivered')),
            notes          TEXT,
            placed_by      TEXT DEFAULT 'management',
            placed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("created patient_orders")

    # ── 6. complaints (updated schema) ────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE complaints (
            complaint_id       SERIAL PRIMARY KEY,
            complaint_category TEXT NOT NULL CHECK (complaint_category IN ('general', 'treatment')),
            -- TYPE 1 (general) fields
            patient_name       TEXT NOT NULL,
            contact_number     TEXT,
            -- TYPE 2 (treatment) fields -- NULL for general complaints
            patient_id         INT  REFERENCES patients(patient_id) DEFAULT NULL,
            appointment_id     INT  REFERENCES appointments(appointment_id) DEFAULT NULL,
            date_of_birth      TEXT DEFAULT NULL,
            treatment_name     TEXT DEFAULT NULL,
            dentist_name       TEXT DEFAULT NULL,
            treatment_date     TEXT DEFAULT NULL,
            treatment_time     TEXT DEFAULT NULL,
            additional_info    TEXT DEFAULT NULL,
            -- shared
            complaint_text     TEXT NOT NULL,
            status             TEXT DEFAULT 'pending',
            created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("created complaints")

    # ── 7. suppliers (NEW) ────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE suppliers (
            supplier_id    SERIAL PRIMARY KEY,
            company_name   TEXT NOT NULL UNIQUE,
            specialty      TEXT,
            contact_number TEXT,
            email          TEXT,
            is_active      BOOLEAN DEFAULT TRUE,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("created suppliers")

    # Seed 5 known suppliers
    suppliers_seed = [
        ("AusDental Labs Pty Ltd",      "Crowns, Bridges, Veneers, Tooth Caps",          "03 9100 2211", "orders@ausdentalabs.com.au"),
        ("MedPro Orthodontics",          "Braces, Clear Aligners, Retainers",             "03 9200 4455", "supply@medproortho.com.au"),
        ("Southern Implant Supply Co.",  "Dental Implants, Abutments, Implant Crowns",    "03 9300 6677", "logistics@southernimplant.com.au"),
        ("PrecisionDenture Works",       "Dentures, Partial Plates, Immediate Dentures",  "03 9400 8899", "production@precisiondenture.com.au"),
        ("OralCraft Technologies",       "Custom Mouthguards, Night Guards, Sports Guards","03 9500 1122", "dispatch@oralcraft.com.au"),
    ]
    for row in suppliers_seed:
        cursor.execute(
            """
            INSERT INTO suppliers (company_name, specialty, contact_number, email)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (company_name) DO NOTHING
            """,
            row,
        )
    conn.commit()
    print("seeded 5 suppliers")

    # ── 8. business_logs ──────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE business_logs (
            log_id          SERIAL PRIMARY KEY,
            caller_name     TEXT,
            company_name    TEXT,
            contact_number  TEXT,
            purpose         TEXT,
            full_call_notes TEXT,
            logged_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("created business_logs")

    cursor.close()
    conn.close()
    print("\nAll tables created and seeded successfully.")


if __name__ == "__main__":
    create_tables()