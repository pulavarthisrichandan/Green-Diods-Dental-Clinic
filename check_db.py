import sys
from datetime import date
from db.db_connection import db_cursor

SEPARATOR = "=" * 80

def print_header(title: str):
    print("\n" + SEPARATOR)
    print(f"  {title}")
    print(SEPARATOR)


def safe_count(table: str, where_sql: str = "", params: tuple = ()):
    """
    Safely count rows in a table. If the table doesn't exist, return None.
    """
    try:
        with db_cursor() as (cursor, conn):
            sql = f"SELECT COUNT(*) FROM {table} {where_sql}"
            cursor.execute(sql, params)
            return cursor.fetchone()[0]
    except Exception as e:
        print(f"  {table:<25} : ERROR or MISSING — {e}")
        return None


def show_summary():
    print_header("DATABASE SUMMARY — DentalBot v2")

    tables = [
        ("patients", "Patients"),
        ("appointments", "Appointments"),
        ("complaints", "Complaints"),
        ("patient_orders", "Patient Orders"),
        ("business_logs", "Business Call Logs"),
    ]

    for table, label in tables:
        count = safe_count(table)
        if count is not None:
            print(f"  {label:<25} : {count} records")

    # Extra useful stats
    today = date.today()

    try:
        with db_cursor() as (cursor, conn):
            cursor.execute(
                "SELECT COUNT(*) FROM appointments "
                "WHERE preferred_date::date = %s AND status != 'cancelled'",
                (today,)
            )
            today_count = cursor.fetchone()[0]
        print(f"\n  Appointments Today       : {today_count}")
    except Exception as e:
        print(f"\n  Appointments Today       : ERROR — {e}")

    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("SELECT COUNT(*) FROM complaints WHERE status = 'pending'")
            pending = cursor.fetchone()[0]
        print(f"  Pending Complaints       : {pending}")
    except Exception as e:
        print(f"  Pending Complaints       : ERROR — {e}")

    try:
        with db_cursor() as (cursor, conn):
            cursor.execute("SELECT COUNT(*) FROM patient_orders WHERE order_status = 'ready'")
            ready = cursor.fetchone()[0]
        print(f"  Orders Ready             : {ready}")
    except Exception as e:
        print(f"  Orders Ready             : ERROR — {e}")


def clear_test_data():
    """
    Danger zone: clears test data from selected tables.
    Use only in dev.
    """
    print_header("CLEARING TEST DATA (DEV ONLY)")

    tables = [
        "appointments",
        "complaints",
        "patient_orders",
        "business_logs",
    ]

    for table in tables:
        try:
            with db_cursor() as (cursor, conn):
                cursor.execute(f"DELETE FROM {table}")
            print(f"  ✅ Cleared: {table}")
        except Exception as e:
            print(f"  ❌ Failed to clear {table}: {e}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--clear":
        clear_test_data()
    else:
        show_summary()


if __name__ == "__main__":
    main()