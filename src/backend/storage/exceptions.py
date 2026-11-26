"""Custom exceptions for DATN2 MySQL configuration and runtime operations."""

from __future__ import annotations


class DatabaseConfigurationError(RuntimeError):
    """Raised when required MySQL connection settings are missing or invalid."""


class DatabaseOperationError(RuntimeError):
    """Raised when a MySQL connection, migration, or query operation fails."""
