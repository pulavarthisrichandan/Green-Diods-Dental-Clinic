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




import os
import psycopg2
import psycopg2.pool
import threading
from contextlib import contextmanager

# _pool = None
# _pool_lock = threading.Lock()

# def get_pool():
#     global _pool
#     if _pool is None:
#         with _pool_lock:
#             if _pool is None:
#                 db_url = os.getenv("DATABASE_URL")
#                 if not db_url:
#                     raise RuntimeError("DATABASE_URL is not set in environment variables")

#                 test_conn = psycopg2.connect(
#                     db_url,
#                     sslmode="require",
#                     connect_timeout=10
#                 )
#                 test_conn.close()

#                 _pool = psycopg2.pool.SimpleConnectionPool(
#                     1, 10,
#                     dsn=db_url,
#                     sslmode="require",
#                     connect_timeout=10,
#                 )
#     return _pool

# class PooledConnection:
#     def __init__(self, conn, pool):
#         self._conn = conn
#         self._pool = pool

#     def close(self):
#         self._pool.putconn(self._conn)

#     def cursor(self):
#         return self._conn.cursor()

#     def commit(self):
#         return self._conn.commit()

#     def rollback(self):
#         return self._conn.rollback()

#     def __getattr__(self, name):
#         return getattr(self._conn, name)

# def get_db_connection():
#     pool = get_pool()
#     conn = pool.getconn()
#     return PooledConnection(conn, pool)

# @contextmanager
# def db_cursor():
#     conn = None
#     cursor = None
#     try:
#         conn = get_db_connection()
#         cursor = conn.cursor()
#         yield cursor, conn
#         conn.commit()
#     finally:
#         if cursor:
#             cursor.close()
#         if conn:
#             conn.close()


import psycopg2
import socket
from contextlib import contextmanager

DATABASE_URL = "postgresql://postgres:ChandanK%401231@db.krledcpdypdkzqweawqp.supabase.co:5432/postgres"

# Force IPv4 resolution (fixes cloud IPv6 routing issue)
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_only_getaddrinfo(*args, **kwargs):
    infos = _orig_getaddrinfo(*args, **kwargs)
    return [info for info in infos if info[0] == socket.AF_INET]

socket.getaddrinfo = _ipv4_only_getaddrinfo

@contextmanager
def db_cursor():
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            sslmode="require",
            connect_timeout=10
        )
        cursor = conn.cursor()
        yield cursor, conn
        conn.commit()
    except Exception as e:
        print("❌ DB ERROR:", type(e).__name__, e)
        if conn:
            conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()