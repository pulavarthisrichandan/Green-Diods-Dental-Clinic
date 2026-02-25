"""
db/db_connection.py — DentalBot v2

Connection pool for Railway PostgreSQL.
- Uses SimpleConnectionPool (1-10 connections) for performance
- Forces IPv4 to fix Railway cloud routing issues
- Provides both db_cursor() context manager AND get_db_connection()
  so both old and new executor patterns work
"""

import os
import socket
import psycopg2
import psycopg2.pool
import threading
import traceback
from contextlib import contextmanager

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE URL
# ─────────────────────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:NtHJJyplErqWtyuOVmyRqIftIiAPCUwL@shinkansen.proxy.rlwy.net:28107/railway"
)

# ─────────────────────────────────────────────────────────────────────────────
# FORCE IPv4 — fixes Railway cloud IPv6 routing issue
# Without this, connections randomly fail on Railway's network
# ─────────────────────────────────────────────────────────────────────────────

_orig_getaddrinfo = socket.getaddrinfo

def _ipv4_only_getaddrinfo(*args, **kwargs):
    infos = _orig_getaddrinfo(*args, **kwargs)
    ipv4  = [info for info in infos if info[0] == socket.AF_INET]
    return ipv4 if ipv4 else infos   # fallback to all if no IPv4 found

socket.getaddrinfo = _ipv4_only_getaddrinfo

# ─────────────────────────────────────────────────────────────────────────────
# CONNECTION POOL
# Reuses connections across calls instead of opening a new one every time.
# Handles up to 10 concurrent DB operations (enough for multiple live calls).
# ─────────────────────────────────────────────────────────────────────────────

_pool      = None
_pool_lock = threading.Lock()

def get_pool() -> psycopg2.pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                if not DATABASE_URL:
                    raise RuntimeError("DATABASE_URL is not set in environment variables")

                print("[DB] Initialising connection pool...")
                _pool = psycopg2.pool.SimpleConnectionPool(
                    1,    # min connections — always keep 1 alive
                    10,   # max connections — handles concurrent callers
                    dsn=DATABASE_URL,
                    sslmode="prefer",
                    connect_timeout=10
                )
                print("[DB] ✅ Connection pool ready (1–10 connections)")
    return _pool


def get_db_connection():
    """
    Get a raw connection from the pool.
    Caller is responsible for conn.commit() and conn.close() (returns to pool).
    Used by old-style executors.
    """
    return get_pool().getconn()


def release_db_connection(conn):
    """Return a connection back to the pool."""
    try:
        get_pool().putconn(conn)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# db_cursor() CONTEXT MANAGER
# Used by all new-style executors with `with db_cursor() as (cursor, conn):`
# Automatically commits on success, rolls back on error, returns conn to pool.
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def db_cursor():
    conn   = None
    cursor = None
    try:
        conn   = get_pool().getconn()
        cursor = conn.cursor()
        yield cursor, conn
        conn.commit()    # ✅ auto-commit on clean exit
    except Exception as e:
        print(f"❌ DB ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
        if conn:
            conn.rollback()   # ✅ rollback on any error
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            get_pool().putconn(conn)   # ✅ return to pool, not close()
