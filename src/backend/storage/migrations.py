"""Idempotent MySQL DDL creation, column migrations, backfills, and indexes."""

from __future__ import annotations

from typing import Any

from src.backend.config import PARKING_FEE_VND


def _column_migrations(fee_vnd: int) -> list[tuple[str, str]]:
    fee = int(fee_vnd)
    return [
        (
            "plate_key",
            "ALTER TABLE plate_recognition_history "
            "ADD COLUMN plate_key VARCHAR(32) NULL AFTER plate_number",
        ),
        (
            "direction",
            "ALTER TABLE plate_recognition_history "
            "ADD COLUMN direction VARCHAR(8) NOT NULL DEFAULT 'IN' AFTER plate_number",
        ),
        (
            "parking_status",
            "ALTER TABLE plate_recognition_history "
            "ADD COLUMN parking_status VARCHAR(16) NOT NULL DEFAULT 'COMPLETED' AFTER direction",
        ),
        (
            "entry_record_id",
            "ALTER TABLE plate_recognition_history "
            "ADD COLUMN entry_record_id BIGINT UNSIGNED NULL AFTER parking_status",
        ),
        (
            "fee_amount",
            "ALTER TABLE plate_recognition_history "
            f"ADD COLUMN fee_amount INT UNSIGNED NOT NULL DEFAULT {fee} AFTER entry_record_id",
        ),
        (
            "face_detected",
            "ALTER TABLE plate_recognition_history "
            "ADD COLUMN face_detected TINYINT(1) NOT NULL DEFAULT 0",
        ),
        (
            "face_confidence",
            "ALTER TABLE plate_recognition_history "
            "ADD COLUMN face_confidence DECIMAL(5, 4) NULL",
        ),
        (
            "face_embedding",
            "ALTER TABLE plate_recognition_history ADD COLUMN face_embedding BLOB NULL",
        ),
        (
            "face_match_score",
            "ALTER TABLE plate_recognition_history "
            "ADD COLUMN face_match_score DECIMAL(5, 4) NULL",
        ),
        (
            "plate_image",
            "ALTER TABLE plate_recognition_history ADD COLUMN plate_image LONGTEXT NULL",
        ),
        (
            "face_image",
            "ALTER TABLE plate_recognition_history ADD COLUMN face_image LONGTEXT NULL",
        ),
    ]


_INDEX_MIGRATIONS: list[tuple[str, str]] = [
    (
        "idx_plate_recognized_at",
        "ALTER TABLE plate_recognition_history "
        "ADD INDEX idx_plate_recognized_at (plate_number, recognized_at)",
    ),
    (
        "idx_recognized_at",
        "ALTER TABLE plate_recognition_history ADD INDEX idx_recognized_at (recognized_at)",
    ),
    (
        "idx_plate_status",
        "ALTER TABLE plate_recognition_history "
        "ADD INDEX idx_plate_status (plate_number, parking_status)",
    ),
    (
        "idx_status_dir",
        "ALTER TABLE plate_recognition_history "
        "ADD INDEX idx_status_dir (parking_status, direction)",
    ),
    (
        "idx_plate_key_dir_status",
        "ALTER TABLE plate_recognition_history "
        "ADD INDEX idx_plate_key_dir_status (plate_key, direction, parking_status)",
    ),
    (
        "idx_entry_record_id",
        "ALTER TABLE plate_recognition_history "
        "ADD INDEX idx_entry_record_id (entry_record_id)",
    ),
]


def ensure_mysql_table(cursor: Any, fee_vnd: int = PARKING_FEE_VND) -> None:
    """Create plate_recognition_history if absent and apply idempotent migrations."""
    fee = int(fee_vnd)
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS plate_recognition_history (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
            plate_number VARCHAR(32) NOT NULL,
            plate_key VARCHAR(32) NULL,
            direction VARCHAR(8) NOT NULL DEFAULT 'IN',
            parking_status VARCHAR(16) NOT NULL DEFAULT 'IN_PARKING',
            entry_record_id BIGINT UNSIGNED NULL,
            fee_amount INT UNSIGNED NOT NULL DEFAULT {fee},
            recognized_at DATETIME NOT NULL,
            vote_count SMALLINT UNSIGNED NOT NULL,
            sample_count SMALLINT UNSIGNED NOT NULL,
            consensus_rate DECIMAL(5, 4) NOT NULL,
            face_detected TINYINT(1) NOT NULL DEFAULT 0,
            face_confidence DECIMAL(5, 4) NULL,
            face_embedding BLOB NULL COMMENT '512 x float32 L2-normalized FaceNet vector (2048 bytes)',
            face_match_score DECIMAL(5, 4) NULL,
            plate_image LONGTEXT NULL COMMENT 'JPEG Data URL (max 360x180, quality 92)',
            face_image LONGTEXT NULL COMMENT 'JPEG Data URL (max 320x320, pad_ratio 0.22, quality 92)',
            camera_index SMALLINT UNSIGNED NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_plate_recognized_at (plate_number, recognized_at),
            INDEX idx_recognized_at (recognized_at),
            INDEX idx_plate_status (plate_number, parking_status),
            INDEX idx_status_dir (parking_status, direction),
            INDEX idx_plate_key_dir_status (plate_key, direction, parking_status),
            INDEX idx_entry_record_id (entry_record_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    cursor.execute("SHOW COLUMNS FROM plate_recognition_history")
    existing_columns = {
        row["Field"] if isinstance(row, dict) else row[0]
        for row in (cursor.fetchall() or [])
    }
    for col_name, ddl in _column_migrations(fee):
        if col_name not in existing_columns:
            cursor.execute(ddl)

    cursor.execute(
        "UPDATE plate_recognition_history "
        "SET plate_key = UPPER(REPLACE(REPLACE(plate_number, '-', ''), '.', '')) "
        "WHERE plate_key IS NULL OR plate_key = ''"
    )
    cursor.execute(
        "UPDATE plate_recognition_history "
        "SET fee_amount = 0 "
        "WHERE direction = 'OUT' AND fee_amount <> 0"
    )

    cursor.execute("SHOW INDEX FROM plate_recognition_history")
    existing_indexes = {
        row["Key_name"] if isinstance(row, dict) else row[2]
        for row in (cursor.fetchall() or [])
    }
    for idx_name, ddl in _INDEX_MIGRATIONS:
        if idx_name not in existing_indexes:
            cursor.execute(ddl)
