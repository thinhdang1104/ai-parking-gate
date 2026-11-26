-- DATN2 MySQL 8.0 Schema
-- 100% compatible with legacy DATN `plate_recognition_history` table and indexes.
-- All `recognized_at` timestamps are stored as naive Vietnam local time (UTC+7).

CREATE TABLE IF NOT EXISTS plate_recognition_history (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    plate_number VARCHAR(32) NOT NULL,
    plate_key VARCHAR(32) NULL,
    direction VARCHAR(8) NOT NULL DEFAULT 'IN',
    parking_status VARCHAR(16) NOT NULL DEFAULT 'IN_PARKING',
    entry_record_id BIGINT UNSIGNED NULL,
    fee_amount INT UNSIGNED NOT NULL DEFAULT 2000,
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
