# db_console.py
# Simple interactive DB console for DentalBot v2

from datetime import date
from db.db_connection import db_cursor

def view_patients():
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT patient_id, first_name, last_name, date_of_birth, contact_number
            FROM patients
            ORDER BY patient_id DESC
            LIMIT 20
        """)
        rows = cursor.fetchall()

    print("\n=== Patients ===")
    for r in rows:
        print(r)
    print(f"Total shown: {len(rows)}")


def view_appointments():
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT appointment_id, patient_id, preferred_treatment,
                   preferred_date, preferred_time, preferred_dentist, status
            FROM appointments
            ORDER BY appointment_id DESC
            LIMIT 20
        """)
        rows = cursor.fetchall()

    print("\n=== Appointments ===")
    for r in rows:
        print(r)
    print(f"Total shown: {len(rows)}")


def view_appointments_by_patient():
    pid = input("Enter patient_id: ").strip()
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT appointment_id, preferred_treatment, preferred_date,
                   preferred_time, preferred_dentist, status
            FROM appointments
            WHERE patient_id = %s
            ORDER BY preferred_date DESC
        """, (pid,))
        rows = cursor.fetchall()

    print(f"\n=== Appointments for Patient {pid} ===")
    for r in rows:
        print(r)
    print(f"Total: {len(rows)}")


def view_complaints():
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT complaint_id, patient_name, complaint_text, status, created_at
            FROM complaints
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = cursor.fetchall()

    print("\n=== Complaints ===")
    for r in rows:
        print(r)
    print(f"Total shown: {len(rows)}")


def view_business_logs():
    with db_cursor() as (cursor, conn):
        cursor.execute("""
            SELECT id, caller_name, company_name, purpose, created_at
            FROM business_logs
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = cursor.fetchall()

    print("\n=== Business Call Logs ===")
    for r in rows:
        print(r)
    print(f"Total shown: {len(rows)}")


def create_test_patient():
    first_name = input("First name: ").strip()
    last_name = input("Last name: ").strip()
    dob = input("DOB (YYYY-MM-DD): ").strip()
    phone = input("Contact number: ").strip()

    with db_cursor() as (cursor, conn):
        cursor.execute("""
            INSERT INTO patients (first_name, last_name, date_of_birth, contact_number)
            VALUES (%s, %s, %s, %s)
            RETURNING patient_id
        """, (first_name, last_name, dob, phone))
        pid = cursor.fetchone()[0]

    print(f"✅ Created patient with ID: {pid}")


def create_test_appointment():
    pid = input("Patient ID: ").strip()
    treatment = input("Treatment: ").strip()
    date_str = input("Date (YYYY-MM-DD): ").strip()
    time_str = input("Time (HH:MM): ").strip()
    dentist = input("Dentist name: ").strip()

    with db_cursor() as (cursor, conn):
        cursor.execute("""
            INSERT INTO appointments
            (patient_id, preferred_treatment, preferred_date, preferred_time, preferred_dentist, status)
            VALUES (%s, %s, %s, %s, %s, 'confirmed')
            RETURNING appointment_id
        """, (pid, treatment, date_str, time_str, dentist))
        appt_id = cursor.fetchone()[0]

    print(f"✅ Created appointment with ID: {appt_id}")


def menu():
    print("\n================= DentalBot DB Console =================")
    print("1. View Patients")
    print("2. View Appointments")
    print("3. View Appointments for a Patient")
    print("4. View Complaints")
    print("5. View Business Call Logs")
    print("6. Create Test Patient")
    print("7. Create Test Appointment")
    print("0. Exit")
    print("=======================================================")


def main():
    while True:
        menu()
        choice = input("Select option: ").strip()

        if choice == "1":
            view_patients()
        elif choice == "2":
            view_appointments()
        elif choice == "3":
            view_appointments_by_patient()
        elif choice == "4":
            view_complaints()
        elif choice == "5":
            view_business_logs()
        elif choice == "6":
            create_test_patient()
        elif choice == "7":
            create_test_appointment()
        elif choice == "0":
            print("Bye 👋")
            break
        else:
            print("❌ Invalid option. Try again.")


if __name__ == "__main__":
    main()