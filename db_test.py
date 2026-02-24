import psycopg2

# 🔴 PUT YOUR FULL DATABASE URL HERE (with %40 for @ in password)
DATABASE_URL = "postgresql://postgres:ChandanK%401231@db.krledcpdypdkzqweawqp.supabase.co:5432/postgres"

print("Testing DB connection...")
print("URL (masked):", DATABASE_URL.split("@")[0] + "@...")

try:
    conn = psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        connect_timeout=10
    )
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()
    print("✅ Connected to DB. Postgres version:", version)

    cur.execute("SELECT now();")
    print("✅ DB time:", cur.fetchone())

    cur.close()
    conn.close()
    print("🎉 DB connection SUCCESS")

except Exception as e:
    print("❌ DB connection FAILED")
    print(type(e).__name__, e)