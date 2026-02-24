# import psycopg2
# import psycopg2.pool
# import os

# _pool = None

# def get_pool():
#     global _pool
#     if _pool is None:
#         _pool = psycopg2.pool.SimpleConnectionPool(
#             1,   # min connections
#             10,  # max connections
#             host=os.getenv("DB_HOST"),
#             database=os.getenv("DB_NAME"),
#             user=os.getenv("DB_USER"),
#             password=os.getenv("DB_PASSWORD")
#         )
#     return _pool

# def get_db_connection():
#     return get_pool().getconn()

# def release_db_connection(conn):
#     get_pool().putconn(conn)


# db/db_connection.py

import os
import psycopg2
import psycopg2.pool
import threading

_pool = None
_pool_lock = threading.Lock()

def get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                db_url = os.getenv("DATABASE_URL")
                if not db_url:
                    raise RuntimeError("DATABASE_URL is not set in environment variables")

                # 🔍 Test connection once (fail fast if Supabase is unreachable)
                test_conn = psycopg2.connect(
                    db_url,
                    sslmode="require",
                    connect_timeout=10
                )
                test_conn.close()

                _pool = psycopg2.pool.SimpleConnectionPool(
                    1, 10,
                    dsn=db_url,
                    sslmode="require",
                    connect_timeout=10,
                )
    return _pool


class PooledConnection:
    """Wraps a psycopg2 connection and returns it to the pool on close()."""

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool

    def close(self):
        # Return connection to pool instead of closing
        self._pool.putconn(self._conn)

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_db_connection():
    pool = get_pool()
    conn = pool.getconn()
    return PooledConnection(conn, pool)


from contextlib import contextmanager

@contextmanager
def db_cursor():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        yield cursor, conn
        conn.commit()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()