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


import psycopg2
import psycopg2.pool
import os

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.SimpleConnectionPool(
        1, 10,
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode=os.getenv("DB_SSLMODE", "require"),
        connect_timeout=5,
    )
    return _pool


class PooledConnection:
    """Wraps a psycopg2 connection and returns it to the pool on close()."""

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool

    # Intercept close() → return to pool instead of destroying
    def close(self):
        self._pool.putconn(self._conn)

    # Forward everything else to the real connection
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


def release_db_connection(conn):
    """Optional explicit release — conn.close() works the same way."""
    conn.close()
