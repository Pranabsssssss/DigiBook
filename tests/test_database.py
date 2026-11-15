from unittest.mock import MagicMock
import pytest
from core.database import DatabasePool


def test_database_pool_configuration():
    """Verify DatabasePool initializes with proper parameters without raising errors."""
    pool = DatabasePool(
        host="localhost",
        port=3306,
        user="test_user",
        password="test_password",
        database="test_db",
        pool_size=2,
    )
    assert pool.host == "localhost"
    assert pool.port == 3306
    assert pool.user == "test_user"
    assert pool.database == "test_db"
    assert pool.pool_size == 2
    assert pool._initialized is False


def test_database_pool_exhaustion_timeout():
    """Verify pool timeout raises TimeoutError when exhausted."""
    pool = DatabasePool(pool_size=1)

    # Use a mock connection with ping and rollback
    mock_conn = MagicMock()
    mock_conn.ping.return_value = True

    pool._pool.put(mock_conn)
    pool._initialized = True

    # Borrow the only connection
    conn = pool.get_connection(timeout=0.1)
    assert conn == mock_conn

    # Next attempt should timeout because pool is empty
    with pytest.raises(TimeoutError):
        pool.get_connection(timeout=0.1)

    # Releasing it makes it available again
    pool.release_connection(conn)
    conn2 = pool.get_connection(timeout=0.1)
    assert conn2 == mock_conn
    pool.release_connection(conn2)
