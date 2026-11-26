"""Direct MySQL connection helper with explicit timeouts and UTC+7 timestamps."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

from src.backend.config import Settings, load_settings
from src.backend.storage.exceptions import (
    DatabaseConfigurationError,
    DatabaseOperationError,
)

try:
    from mysql.connector import Error as _DefaultMySQLError
except ImportError:  # pragma: no cover - fallback when driver is absent
    _DefaultMySQLError = None

VN_TZ = timezone(timedelta(hours=7))

_T = TypeVar("_T")


def now_vn() -> datetime:
    """Return current Vietnam local time (UTC+7) as a naive datetime without microseconds."""
    return datetime.now(VN_TZ).replace(tzinfo=None, microsecond=0)


class MySQLClient:
    """Stateless direct-connect MySQL client (ADR-01: no connection pool)."""

    def __init__(
        self,
        settings: Settings | None = None,
        connector_module: Any = None,
    ) -> None:
        self.settings: Settings = settings if settings is not None else load_settings()
        self._connector_module = connector_module

    def _get_connector(self) -> Any:
        if self._connector_module is not None:
            return self._connector_module
        import mysql.connector

        return mysql.connector

    def error_types(self) -> tuple[type[BaseException], ...]:
        types: list[type[BaseException]] = []
        if isinstance(_DefaultMySQLError, type) and issubclass(
            _DefaultMySQLError, BaseException
        ):
            types.append(_DefaultMySQLError)
        connector_err = getattr(self._connector_module, "Error", None)
        if (
            isinstance(connector_err, type)
            and issubclass(connector_err, BaseException)
            and connector_err not in types
        ):
            types.append(connector_err)
        return tuple(types) if types else (RuntimeError,)

    def build_connection_config(self) -> dict[str, Any]:
        """Validate MySQL settings and build direct connection kwargs with timeouts."""
        missing: list[str] = []
        host = self.settings.mysql_host
        user = self.settings.mysql_user
        database = self.settings.mysql_database
        password = self.settings.mysql_password
        port = self.settings.mysql_port

        if not isinstance(host, str) or not host.strip():
            missing.append("MYSQL_HOST")
        if not isinstance(user, str) or not user.strip():
            missing.append("MYSQL_USER")
        if not isinstance(database, str) or not database.strip():
            missing.append("MYSQL_DATABASE")
        if password is None:
            missing.append("MYSQL_PASSWORD")

        if missing:
            raise DatabaseConfigurationError(
                "Missing required MySQL configuration: " + ", ".join(missing)
            )

        if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
            raise DatabaseConfigurationError(
                f"MYSQL_PORT must be an integer between 1 and 65535, got {port!r}"
            )

        return {
            "host": host.strip(),
            "port": port,
            "user": user.strip(),
            "password": password,
            "database": database.strip(),
            "connection_timeout": int(self.settings.mysql_connect_timeout),
            "read_timeout": int(self.settings.mysql_read_timeout),
            "write_timeout": int(self.settings.mysql_write_timeout),
            "use_pure": True,
        }

    def connect(self) -> Any:
        """Open a fresh direct MySQL connection or raise DatabaseOperationError."""
        config = self.build_connection_config()
        connector = self._get_connector()
        try:
            return connector.connect(**config)
        except self.error_types() as error:
            raise DatabaseOperationError(str(error)) from error

    def run_read_query(self, fn: Callable[[Any], _T]) -> _T:
        """Execute a read callback with a dictionary cursor and close resources safely."""
        connection = self.connect()
        cursor = connection.cursor(dictionary=True)
        try:
            return fn(cursor)
        except self.error_types() as error:
            raise DatabaseOperationError(str(error)) from error
        finally:
            try:
                cursor.close()
            finally:
                connection.close()
