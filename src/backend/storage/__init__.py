"""Storage layer (MySQL repository, migrations, warm RAM mirror, demo seeder)."""

from __future__ import annotations

from src.backend.storage.demo_seeder import (
    DEMO_MARKER_PLATE_KEY,
    build_demo_records,
    seed_demo_records_if_empty,
)
from src.backend.storage.exceptions import (
    DatabaseConfigurationError,
    DatabaseOperationError,
)
from src.backend.storage.migrations import ensure_mysql_table
from src.backend.storage.mysql_client import VN_TZ, MySQLClient, now_vn
from src.backend.storage.repository import ParkingRepository
from src.backend.storage.warm_mirror import WarmDatabaseMirror

__all__ = [
    "DEMO_MARKER_PLATE_KEY",
    "DatabaseConfigurationError",
    "DatabaseOperationError",
    "MySQLClient",
    "ParkingRepository",
    "VN_TZ",
    "WarmDatabaseMirror",
    "build_demo_records",
    "ensure_mysql_table",
    "now_vn",
    "seed_demo_records_if_empty",
]
