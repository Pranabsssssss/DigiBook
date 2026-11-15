import logging
import queue
import threading
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Generator
import pymysql
from pymysql.cursors import DictCursor

from config.settings import (
    DB_HOST,
    DB_PORT,
    DB_USER,
    DB_PASSWORD,
    DB_NAME,
    DB_POOL_SIZE,
)

logger = logging.getLogger("DigiBook.Database")


class DatabasePool:
    """
    Lightweight, thread-safe MySQL connection pool using PyMySQL.
    Designed for Raspberry Pi 3B+ resource constraints.
    """

    def __init__(
        self,
        host: str = DB_HOST,
        port: int = DB_PORT,
        user: str = DB_USER,
        password: str = DB_PASSWORD,
        database: str = DB_NAME,
        pool_size: int = DB_POOL_SIZE,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.pool_size = max(1, pool_size)

        self._pool: queue.Queue = queue.Queue(maxsize=self.pool_size)
        self._lock = threading.Lock()
        self._initialized = False

    def _create_connection(self) -> pymysql.Connection:
        """Create a new database connection with DictCursor."""
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=10,
        )

    def initialize(self):
        """Pre-populate the connection pool."""
        with self._lock:
            if self._initialized:
                return
            for _ in range(self.pool_size):
                conn = self._create_connection()
                self._pool.put(conn)
            self._initialized = True
            logger.info("Initialized DatabasePool with %d connections.", self.pool_size)

    def get_connection(self, timeout: float = 10.0) -> pymysql.Connection:
        """Borrow a connection from the pool."""
        if not self._initialized:
            self.initialize()
        try:
            conn = self._pool.get(block=True, timeout=timeout)
            # Ensure connection is alive; reconnect if severed
            try:
                conn.ping(reconnect=True)
            except Exception as e:
                logger.warning("Connection lost, creating new: %s", e)
                conn = self._create_connection()
            return conn
        except queue.Empty:
            logger.error("Connection pool exhausted (timeout=%.1fs)", timeout)
            raise TimeoutError("Database connection pool exhausted.")

    def release_connection(self, conn: pymysql.Connection):
        """Return a borrowed connection back to the pool."""
        if conn is not None:
            try:
                # Ensure no pending transaction remains uncommitted
                conn.rollback()
            except Exception:
                pass
            try:
                self._pool.put_nowait(conn)
            except queue.Full:
                try:
                    conn.close()
                except Exception:
                    pass

    @contextmanager
    def cursor(self) -> Generator[DictCursor, None, None]:
        """
        Context manager for acquiring a cursor with automatic commit/rollback.
        Usage:
            with db.cursor() as cur:
                cur.execute("SELECT ...")
                rows = cur.fetchall()
        """
        conn = self.get_connection()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error("Database query failed: %s", e)
            raise
        finally:
            cur.close()
            self.release_connection(conn)

    def execute(self, sql: str, params: Optional[Any] = None) -> List[Dict[str, Any]]:
        """Execute a query and fetch all rows as a list of dicts."""
        with self.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()

    def execute_one(self, sql: str, params: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """Execute a query and fetch the first matching row or None."""
        with self.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()

    def execute_insert(self, sql: str, params: Optional[Any] = None) -> int:
        """Execute an INSERT statement and return the inserted lastrowid."""
        with self.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.lastrowid

    def execute_commit(self, sql: str, params: Optional[Any] = None) -> int:
        """Execute an UPDATE/DELETE/REPLACE and return rowcount."""
        with self.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.rowcount

    def ping(self) -> bool:
        """Health-check the database connection."""
        try:
            row = self.execute_one("SELECT 1 AS alive")
            return bool(row and row.get("alive") == 1)
        except Exception as e:
            logger.error("Database ping failed: %s", e)
            return False

    def close(self):
        """Close all connections in the pool."""
        with self._lock:
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    conn.close()
                except Exception:
                    pass
            self._initialized = False
            logger.info("DatabasePool closed.")


# === Global Singleton Instance ===
_db_instance: Optional[DatabasePool] = None
_db_lock = threading.Lock()


def get_db() -> DatabasePool:
    """Obtain or initialize the global DatabasePool singleton."""
    global _db_instance
    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = DatabasePool()
    return _db_instance
