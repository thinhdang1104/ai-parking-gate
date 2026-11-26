"""Integration tests for MySQLClient, migrations, ParkingRepository, and demo seeder."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any
from unittest import mock

import pytest

from src.backend.config import Settings
from src.backend.domain.face_math import embedding_from_bytes
from src.backend.domain.plate_normalizer import clean_plate_key
from src.backend.storage import (
    DEMO_MARKER_PLATE_KEY,
    DatabaseConfigurationError,
    DatabaseOperationError,
    MySQLClient,
    ParkingRepository,
    build_demo_records,
    ensure_mysql_table,
    now_vn,
    seed_demo_records_if_empty,
)


class _FakeMySQLError(Exception):
    pass


class _FakeTableStore:
    """In-memory relational simulator for plate_recognition_history SQL operations."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.next_id: int = 1
        self.uncommitted_rows: list[dict[str, Any]] | None = None
        self.fail_on_insert: bool = False

    def snapshot(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rows]

    def restore(self, snap: list[dict[str, Any]]) -> None:
        self.rows = [dict(r) for r in snap]


class _FakeCursor:
    def __init__(self, store: _FakeTableStore, dictionary: bool = False) -> None:
        self.store = store
        self.dictionary = dictionary
        self.lastrowid = 0
        self._results: list[Any] = []
        self._idx = 0
        self.closed = False

    def execute(self, sql: str, params: Any = None) -> None:
        norm = " ".join(sql.split())
        params = tuple(params) if params is not None else ()
        self._results = []
        self._idx = 0

        if norm.startswith("UPDATE plate_recognition_history SET parking_status = 'COMPLETED'"):
            if self.store.uncommitted_rows is None:
                self.store.uncommitted_rows = self.store.snapshot()
            pk = params[0]
            for row in self.store.rows:
                if (
                    row["plate_key"] == pk
                    and row["direction"] == "IN"
                    and row["parking_status"] == "IN_PARKING"
                ):
                    row["parking_status"] = "COMPLETED"
            return

        if norm.startswith("INSERT INTO plate_recognition_history"):
            if self.store.fail_on_insert:
                raise _FakeMySQLError("Simulated insert error")
            if self.store.uncommitted_rows is None:
                self.store.uncommitted_rows = self.store.snapshot()
            rid = self.store.next_id
            self.store.next_id += 1
            self.lastrowid = rid
            self.store.rows.append(
                {
                    "id": rid,
                    "plate_number": params[0],
                    "plate_key": params[1],
                    "direction": params[2],
                    "parking_status": params[3],
                    "entry_record_id": params[4],
                    "fee_amount": params[5],
                    "recognized_at": params[6],
                    "vote_count": params[7],
                    "sample_count": params[8],
                    "consensus_rate": params[9],
                    "face_detected": params[10],
                    "face_confidence": params[11],
                    "face_embedding": params[12],
                    "face_match_score": params[13],
                    "plate_image": params[14],
                    "face_image": params[15],
                    "camera_index": params[16],
                }
            )
            return

        if "SELECT COUNT(*) FROM plate_recognition_history WHERE plate_key = %s" in norm:
            cnt = sum(1 for r in self.store.rows if r["plate_key"] == params[0])
            self._results = [{"COUNT(*)": cnt} if self.dictionary else (cnt,)]
            return

        if "WHERE plate_key = %s AND direction = 'IN' AND parking_status = 'IN_PARKING'" in norm:
            matches = [
                r
                for r in self.store.rows
                if r["plate_key"] == params[0]
                and r["direction"] == "IN"
                and r["parking_status"] == "IN_PARKING"
            ]
            matches.sort(key=lambda r: (r["recognized_at"], r["id"]), reverse=True)
            if matches:
                r = matches[0]
                item = (
                    {
                        "id": r["id"],
                        "plate_number": r["plate_number"],
                        "recognized_at": r["recognized_at"],
                        "face_embedding": r["face_embedding"],
                    }
                    if self.dictionary
                    else (r["id"], r["plate_number"], r["recognized_at"], r["face_embedding"])
                )
                self._results = [item]
            return

        if "AS total," in norm and "AS in_parking," in norm:
            today_start = params[0]
            self._results = [
                {
                    "total": len(self.store.rows),
                    "today": sum(1 for r in self.store.rows if r["recognized_at"] >= today_start),
                    "in_parking": sum(
                        1
                        for r in self.store.rows
                        if r["direction"] == "IN" and r["parking_status"] == "IN_PARKING"
                    ),
                    "total_in": sum(1 for r in self.store.rows if r["direction"] == "IN"),
                    "total_out": sum(1 for r in self.store.rows if r["direction"] == "OUT"),
                }
            ]
            return

        if "AS tickets_today" in norm:
            t_start, _, m_start, _, y_start, _ = params
            self._results = [
                {
                    "tickets_today": sum(1 for r in self.store.rows if r["recognized_at"] >= t_start and r["direction"] == "IN"),
                    "revenue_today": sum(r["fee_amount"] for r in self.store.rows if r["recognized_at"] >= t_start),
                    "tickets_month": sum(1 for r in self.store.rows if r["recognized_at"] >= m_start and r["direction"] == "IN"),
                    "revenue_month": sum(r["fee_amount"] for r in self.store.rows if r["recognized_at"] >= m_start),
                    "tickets_year": sum(1 for r in self.store.rows if r["recognized_at"] >= y_start and r["direction"] == "IN"),
                    "revenue_year": sum(r["fee_amount"] for r in self.store.rows if r["recognized_at"] >= y_start),
                    "tickets_total": sum(1 for r in self.store.rows if r["direction"] == "IN"),
                    "revenue_total": sum(r["fee_amount"] for r in self.store.rows),
                }
            ]
            return

        if "GROUP BY DATE(recognized_at)" in norm:
            buckets: dict[str, list[Any]] = {}
            for r in self.store.rows:
                if r["direction"] != "IN":
                    continue
                dt = r["recognized_at"]
                key = dt.strftime("%Y-%m-%d")
                b = buckets.setdefault(key, [dt.strftime("%d/%m/%Y"), 0, 0])
                b[1] += 1
                b[2] += r["fee_amount"]
            self._results = [
                {"period_label": v[0], "ticket_count": v[1], "total_vnd": v[2]}
                for _, v in sorted(buckets.items(), reverse=True)
            ]
            return

        if "GROUP BY sort_month" in norm:
            buckets = {}
            for r in self.store.rows:
                if r["direction"] != "IN":
                    continue
                dt = r["recognized_at"]
                key = dt.strftime("%Y-%m")
                b = buckets.setdefault(key, [dt.strftime("%m/%Y"), 0, 0])
                b[1] += 1
                b[2] += r["fee_amount"]
            self._results = [
                {"period_label": v[0], "ticket_count": v[1], "total_vnd": v[2]}
                for _, v in sorted(buckets.items(), reverse=True)
            ]
            return

        if "GROUP BY sort_year" in norm:
            buckets_y: dict[int, list[Any]] = {}
            for r in self.store.rows:
                if r["direction"] != "IN":
                    continue
                yr = r["recognized_at"].year
                b = buckets_y.setdefault(yr, [str(yr), 0, 0])
                b[1] += 1
                b[2] += r["fee_amount"]
            self._results = [
                {"period_label": v[0], "ticket_count": v[1], "total_vnd": v[2]}
                for _, v in sorted(buckets_y.items(), reverse=True)
            ]
            return

        if "SELECT COUNT(*) AS matched FROM plate_recognition_history" in norm:
            filtered = self._filter_rows(norm, params)
            self._results = [{"matched": len(filtered)}]
            return

        if "WHERE id = %s LIMIT 1" in norm:
            rid = int(params[0])
            self._results = [
                self._to_select_row(r) for r in self.store.rows if r["id"] == rid
            ][:1]
            return

        if "WHERE direction = 'OUT' AND entry_record_id = %s" in norm:
            eid = int(params[0])
            matches = [
                r for r in self.store.rows if r["direction"] == "OUT" and r["entry_record_id"] == eid
            ]
            matches.sort(key=lambda r: (r["recognized_at"], r["id"]))
            self._results = [self._to_select_row(r) for r in matches[:1]]
            return

        if "SELECT id, recognized_at FROM plate_recognition_history" in norm:
            pk, dt1, dt2, rid = params
            matches = [
                r
                for r in self.store.rows
                if r["plate_key"] == pk
                and r["direction"] == "IN"
                and (r["recognized_at"] > dt1 or (r["recognized_at"] == dt2 and r["id"] > rid))
            ]
            matches.sort(key=lambda r: (r["recognized_at"], r["id"]))
            self._results = [
                {"id": r["id"], "recognized_at": r["recognized_at"]} for r in matches[:1]
            ]
            return

        if "AND direction = 'IN' AND (recognized_at < %s" in norm:
            pk, dt1, dt2, rid = params
            matches = [
                r
                for r in self.store.rows
                if r["plate_key"] == pk
                and r["direction"] == "IN"
                and (r["recognized_at"] < dt1 or (r["recognized_at"] == dt2 and r["id"] < rid))
            ]
            matches.sort(key=lambda r: (r["recognized_at"], r["id"]), reverse=True)
            self._results = [self._to_select_row(r) for r in matches[:1]]
            return

        if "AND direction = 'OUT' AND (recognized_at > %s" in norm:
            if len(params) == 7:
                pk, dt1, dt2, rid, ndt1, ndt2, nrid = params
                matches = [
                    r
                    for r in self.store.rows
                    if r["plate_key"] == pk
                    and r["direction"] == "OUT"
                    and (r["recognized_at"] > dt1 or (r["recognized_at"] == dt2 and r["id"] > rid))
                    and (r["recognized_at"] < ndt1 or (r["recognized_at"] == ndt2 and r["id"] < nrid))
                ]
            else:
                pk, dt1, dt2, rid = params
                matches = [
                    r
                    for r in self.store.rows
                    if r["plate_key"] == pk
                    and r["direction"] == "OUT"
                    and (r["recognized_at"] > dt1 or (r["recognized_at"] == dt2 and r["id"] > rid))
                ]
            matches.sort(key=lambda r: (r["recognized_at"], r["id"]))
            self._results = [self._to_select_row(r) for r in matches[:1]]
            return

        if "LIMIT %s OFFSET %s" in norm:
            limit_val, offset_val = int(params[-2]), int(params[-1])
            filter_params = params[:-2]
            filtered = self._filter_rows(norm, filter_params)
            filtered.sort(key=lambda r: (r["recognized_at"], r["id"]), reverse=True)
            m = re.search(r"face_match_score < ([0-9.]+)", norm)
            if m:
                thresh = float(m.group(1))
                if "THEN 0 ELSE 1" in norm:
                    filtered.sort(
                        key=lambda r: 0
                        if (r["face_match_score"] is not None and r["face_match_score"] < thresh)
                        else 1
                    )
                else:
                    filtered.sort(
                        key=lambda r: 1
                        if (r["face_match_score"] is not None and r["face_match_score"] < thresh)
                        else 0
                    )
            sliced = filtered[offset_val : offset_val + limit_val]
            self._results = [self._to_select_row(r) for r in sliced]
            return

        if "ORDER BY recognized_at ASC, id ASC" in norm:
            matches = [
                r
                for r in self.store.rows
                if r["direction"] == "IN" and r["parking_status"] == "IN_PARKING"
            ]
            matches.sort(key=lambda r: (r["recognized_at"], r["id"]))
            self._results = [dict(r) for r in matches]
            return

        if "SELECT id, plate_image, face_image" in norm:
            limit_val = int(params[0])
            ordered = sorted(self.store.rows, key=lambda r: (r["recognized_at"], r["id"]), reverse=True)
            self._results = [
                {"id": r["id"], "plate_image": r["plate_image"], "face_image": r["face_image"]}
                for r in ordered[:limit_val]
            ]
            return

        if "FROM plate_recognition_history ORDER BY recognized_at DESC, id DESC" in norm:
            ordered = sorted(self.store.rows, key=lambda r: (r["recognized_at"], r["id"]), reverse=True)
            self._results = [self._to_select_row(r) for r in ordered]
            return

    def _filter_rows(self, norm: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        rows = list(self.store.rows)
        if "plate_key LIKE %s" in norm:
            needle = params[0].strip("%")
            rows = [r for r in rows if needle in r["plate_key"]]
        if "direction = 'IN' AND parking_status = 'IN_PARKING'" in norm:
            rows = [
                r for r in rows if r["direction"] == "IN" and r["parking_status"] == "IN_PARKING"
            ]
        elif "direction = 'IN'" in norm:
            rows = [r for r in rows if r["direction"] == "IN"]
        elif "direction = 'OUT'" in norm:
            rows = [r for r in rows if r["direction"] == "OUT"]
        return rows

    @staticmethod
    def _to_select_row(r: dict[str, Any]) -> dict[str, Any]:
        out = dict(r)
        out["face_embedding"] = 1 if r.get("face_embedding") is not None else 0
        return out

    def fetchone(self) -> Any:
        if self._idx >= len(self._results):
            return None
        val = self._results[self._idx]
        self._idx += 1
        return val

    def fetchall(self) -> list[Any]:
        res = self._results[self._idx :]
        self._idx = len(self._results)
        return res

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self, store: _FakeTableStore) -> None:
        self.store = store
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    def cursor(self, dictionary: bool = False) -> _FakeCursor:
        return _FakeCursor(self.store, dictionary=dictionary)

    def commit(self) -> None:
        self.committed += 1
        self.store.uncommitted_rows = None

    def rollback(self) -> None:
        self.rolled_back += 1
        if self.store.uncommitted_rows is not None:
            self.store.rows = self.store.uncommitted_rows
            self.store.uncommitted_rows = None

    def close(self) -> None:
        self.closed = True


class _FakeConnector:
    Error = _FakeMySQLError

    def __init__(self, store: _FakeTableStore) -> None:
        self.store = store
        self.connect_calls: list[dict[str, Any]] = []
        self.connections: list[_FakeConnection] = []
        self.fail_connect = False

    def connect(self, **kwargs: Any) -> _FakeConnection:
        self.connect_calls.append(kwargs)
        if self.fail_connect:
            raise _FakeMySQLError("Connection refused")
        conn = _FakeConnection(self.store)
        self.connections.append(conn)
        return conn


def _make_record(
    plate: str = "59V1-79379",
    direction: str = "IN",
    recognized_at: datetime | None = None,
    embedding: list[float] | None = None,
    match_score: float | None = None,
    entry_record_id: int | None = None,
) -> dict[str, Any]:
    return {
        "plate_number": plate,
        "direction": direction,
        "entry_record_id": entry_record_id,
        "recognized_at": recognized_at or datetime(2026, 11, 26, 8, 0, 0),
        "vote_count": 3,
        "sample_count": 3,
        "consensus_rate": 1.0,
        "face_detected": True,
        "face_confidence": 0.96,
        "face_embedding": embedding,
        "face_match_score": match_score,
        "plate_image": "data:image/jpeg;base64,PLATE",
        "face_image": "data:image/jpeg;base64,FACE",
        "camera_index": 2 if direction == "IN" else 1,
    }


def test_mysql_client_validation_timeouts_and_error_wrapping() -> None:
    now = now_vn()
    assert now.tzinfo is None
    assert now.microsecond == 0

    bad_host = MySQLClient(Settings(mysql_host=""))
    with pytest.raises(DatabaseConfigurationError, match="MYSQL_HOST"):
        bad_host.build_connection_config()

    bad_port = MySQLClient(Settings(mysql_port=70000))
    with pytest.raises(DatabaseConfigurationError, match="MYSQL_PORT"):
        bad_port.build_connection_config()

    bad_pwd = MySQLClient(Settings(mysql_password=None))  # type: ignore[arg-type]
    with pytest.raises(DatabaseConfigurationError, match="MYSQL_PASSWORD"):
        bad_pwd.build_connection_config()

    store = _FakeTableStore()
    connector = _FakeConnector(store)
    client = MySQLClient(
        Settings(
            mysql_host="127.0.0.1",
            mysql_port=3306,
            mysql_user="parking",
            mysql_password="pw",
            mysql_database="parking_db",
        ),
        connector_module=connector,
    )
    cfg = client.build_connection_config()
    assert cfg == {
        "host": "127.0.0.1",
        "port": 3306,
        "user": "parking",
        "password": "pw",
        "database": "parking_db",
        "connection_timeout": 8,
        "read_timeout": 10,
        "write_timeout": 10,
        "use_pure": True,
    }

    result = client.run_read_query(lambda cur: "ok")
    assert result == "ok"
    assert connector.connections[-1].closed is True

    def _boom(_cur: Any) -> None:
        raise _FakeMySQLError("read failed")

    with pytest.raises(DatabaseOperationError, match="read failed"):
        client.run_read_query(_boom)
    assert connector.connections[-1].closed is True

    connector.fail_connect = True
    with pytest.raises(DatabaseOperationError, match="Connection refused"):
        client.connect()


def test_ensure_mysql_table_ddl_migrations_and_indexes() -> None:
    executed: list[str] = []
    cur = mock.MagicMock()
    cur.execute.side_effect = lambda sql, params=None: executed.append(" ".join(sql.split()))
    # Simulate legacy table missing plate_key, entry_record_id, and 5 indexes
    cur.fetchall.side_effect = [
        [{"Field": "id"}, {"Field": "plate_number"}, {"Field": "direction"}],
        [{"Key_name": "PRIMARY"}, {"Key_name": "idx_plate_recognized_at"}],
    ]

    ensure_mysql_table(cur, fee_vnd=2000)

    joined = "\n".join(executed)
    assert "CREATE TABLE IF NOT EXISTS plate_recognition_history" in joined
    assert "ADD COLUMN plate_key VARCHAR(32) NULL" in joined
    assert "ADD COLUMN entry_record_id BIGINT UNSIGNED NULL" in joined
    assert "ADD COLUMN fee_amount INT UNSIGNED NOT NULL DEFAULT 2000" in joined
    assert "SET plate_key = UPPER(REPLACE(REPLACE(plate_number, '-', ''), '.', ''))" in joined
    assert "SET fee_amount = 0 WHERE direction = 'OUT' AND fee_amount <> 0" in joined
    for idx_name in (
        "idx_recognized_at",
        "idx_plate_status",
        "idx_status_dir",
        "idx_plate_key_dir_status",
        "idx_entry_record_id",
    ):
        assert f"ADD INDEX {idx_name}" in joined
    assert "ADD INDEX idx_plate_recognized_at" not in joined


def test_repository_insert_match_score_completed_and_rollback() -> None:
    store = _FakeTableStore()
    connector = _FakeConnector(store)
    client = MySQLClient(Settings(), connector_module=connector)
    repo = ParkingRepository(client, now_fn=lambda: datetime(2026, 11, 26, 12, 0, 0))

    emb = [1.0 / (512 ** 0.5)] * 512
    in_id, in_score = repo.insert_plate_record(
        _make_record("59V1-79379", "IN", datetime(2026, 11, 26, 8, 0, 0), embedding=emb)
    )
    assert in_id == 1
    assert in_score is None
    assert store.rows[0]["parking_status"] == "IN_PARKING"
    assert store.rows[0]["fee_amount"] == 2000
    assert store.rows[0]["plate_key"] == "59V179379"
    assert embedding_from_bytes(store.rows[0]["face_embedding"]) == pytest.approx(emb, abs=1e-5)

    active = repo.find_active_parking_session("59v179379")
    assert active is not None
    assert active["id"] == 1
    assert active["recognized_at"] == "2026-11-26 08:00:00"

    # OUT computes cosine similarity and marks prior IN as COMPLETED
    out_rec = _make_record("59V1-79379", "OUT", datetime(2026, 11, 26, 10, 0, 0), embedding=emb)
    out_id, out_score = repo.insert_plate_record(out_rec)
    assert out_id == 2
    assert out_score == pytest.approx(1.0, abs=1e-5)
    assert out_rec["entry_record_id"] == 1
    assert store.rows[0]["parking_status"] == "COMPLETED"
    assert store.rows[1]["parking_status"] == "EXITED"
    assert store.rows[1]["fee_amount"] == 0
    assert repo.find_active_parking_session("59V1-79379") is None

    # DB error rolls back prior UPDATE so active IN_PARKING is preserved
    in_id2, _ = repo.insert_plate_record(
        _make_record("30T4-1975", "IN", datetime(2026, 11, 26, 11, 0, 0), embedding=emb)
    )
    assert in_id2 == 3
    store.fail_on_insert = True
    with pytest.raises(DatabaseOperationError, match="Simulated insert error"):
        repo.insert_plate_record(
            _make_record("30T4-1975", "OUT", datetime(2026, 11, 26, 11, 30, 0), embedding=emb)
        )
    assert connector.connections[-1].rolled_back == 1
    assert connector.connections[-1].closed is True
    assert store.rows[2]["parking_status"] == "IN_PARKING"


def test_repository_overview_revenue_query_budget_and_session_cases() -> None:
    store = _FakeTableStore()
    connector = _FakeConnector(store)
    fixed_now = datetime(2026, 11, 26, 15, 0, 0)
    client = MySQLClient(Settings(), connector_module=connector)
    repo = ParkingRepository(client, now_fn=lambda: fixed_now)

    # Seed IN/OUT with entry_record_id, legacy IN/OUT without entry_record_id, and active IN_PARKING
    emb = [0.2] * 512
    # 1 & 2: paired via entry_record_id, mismatch score
    repo.insert_plate_record(_make_record("59A1-11111", "IN", datetime(2026, 11, 25, 8, 0, 0), emb))
    repo.insert_plate_record(
        _make_record("59A1-11111", "OUT", datetime(2026, 11, 25, 10, 0, 0), emb, match_score=0.41, entry_record_id=1)
    )
    # 3 & 4: legacy pair without entry_record_id, matched score
    repo.insert_plate_record(_make_record("60B2-22222", "IN", datetime(2026, 11, 26, 8, 0, 0), emb))
    repo.insert_plate_record(
        _make_record("60B2-22222", "OUT", datetime(2026, 11, 26, 9, 0, 0), emb, match_score=0.92, entry_record_id=None)
    )
    # 5: active IN_PARKING
    repo.insert_plate_record(_make_record("72C1-60266", "IN", datetime(2026, 11, 26, 12, 0, 0), emb))
    # 6: COMPLETED without OUT (e.g., closed by second IN)
    repo.insert_plate_record(_make_record("59X3-77777", "IN", datetime(2026, 11, 26, 7, 0, 0), emb))
    repo.insert_plate_record(_make_record("59X3-77777", "IN", datetime(2026, 11, 26, 13, 0, 0), emb))

    # Overview with revenue
    ov = repo.fetch_overview(include_revenue=True, sort_by="mismatch_first")
    assert ov["stats"] == {
        "total_records": 7,
        "today_records": 5,
        "in_parking": 2,
        "total_in": 5,
        "total_out": 2,
    }
    assert ov["revenue"]["today"] == {"tickets": 4, "revenue": 8000}
    assert ov["revenue"]["total"] == {"tickets": 5, "revenue": 10000}
    assert ov["records"][0]["id"] == 2  # mismatch_first puts id=2 (0.41) first
    # ADR-02: raw dict only, no Vietnamese UI labels
    assert "Biển số" not in ov["records"][0]
    assert "Luồng" not in ov["records"][0]
    assert set(ov["records"][0].keys()) == {
        "id", "plate_number", "plate_key", "direction", "parking_status",
        "entry_record_id", "fee_amount", "recognized_at", "vote_count",
        "sample_count", "consensus_rate", "face_detected", "face_confidence",
        "face_embedding", "face_match_score", "plate_image", "face_image", "camera_index",
    }

    # Session cases
    case_out = repo.fetch_parking_session_case(2)
    assert case_out is not None
    assert case_out["checkin_record"]["id"] == 1
    assert case_out["checkout_record"]["id"] == 2
    assert "checkin_row" not in case_out

    case_legacy_in = repo.fetch_parking_session_case(3)
    assert case_legacy_in is not None
    assert case_legacy_in["checkin_record"]["id"] == 3
    assert case_legacy_in["checkout_record"]["id"] == 4

    case_missing_exit = repo.fetch_parking_session_case(6)
    assert case_missing_exit is not None
    assert case_missing_exit["checkout_record"] is None
    assert case_missing_exit["session_closed_missing_exit"] is True

    assert repo.fetch_parking_session_case(9999) is None

    # Verify SQL query budget optimization on IN_PARKING short-circuit and pagination
    executed_sqls: list[str] = []
    fake_cur = mock.MagicMock()
    fake_cur.execute.side_effect = lambda sql, params=None: executed_sqls.append(" ".join(sql.split()))
    fake_cur.fetchone.return_value = {
        "id": 5, "plate_number": "72C1-60266", "plate_key": "72C160266",
        "direction": "IN", "parking_status": "IN_PARKING", "entry_record_id": None,
        "fee_amount": 2000, "recognized_at": fixed_now, "vote_count": 3,
        "sample_count": 3, "consensus_rate": 1.0, "face_detected": 1,
        "face_confidence": 0.96, "face_embedding": 1, "face_match_score": None,
        "plate_image": None, "face_image": None, "camera_index": 2,
    }
    with mock.patch.object(client, "run_read_query", side_effect=lambda fn: fn(fake_cur)):
        case_in_parking = repo.fetch_parking_session_case(5)
    assert case_in_parking is not None
    assert case_in_parking["in_parking_status"] == "IN_PARKING"
    assert len(executed_sqls) == 1

    executed_sqls.clear()
    fake_cur.fetchone.return_value = {
        "total": 25, "today": 8, "in_parking": 7, "total_in": 16, "total_out": 9,
    }
    fake_cur.fetchall.return_value = []
    with mock.patch.object(client, "run_read_query", side_effect=lambda fn: fn(fake_cur)):
        p1 = repo.fetch_overview(query="", status_filter="in_parking", page=1, include_revenue=False)
        assert len(executed_sqls) == 2
        executed_sqls.clear()
        p2 = repo.fetch_overview(
            query="",
            status_filter="all",
            page=2,
            include_stats=False,
            include_revenue=False,
            known_stats=p1["stats"],
        )
        assert p2["matched"] == 25
        assert p2["page"] == 2
        assert len(executed_sqls) == 1


def test_initialize_and_demo_seeder_idempotency() -> None:
    records = build_demo_records(now=datetime(2026, 11, 26, 14, 0, 0))
    assert len(records) == 38
    assert sum(1 for r in records if r["direction"] == "IN") == 22
    assert sum(1 for r in records if r["direction"] == "OUT") == 16
    assert any(clean_plate_key(r["plate_number"]) == DEMO_MARKER_PLATE_KEY for r in records)

    store = _FakeTableStore()
    connector = _FakeConnector(store)
    client = MySQLClient(Settings(), connector_module=connector)
    repo = ParkingRepository(client)

    assert seed_demo_records_if_empty(repo, enabled=False) == 0
    assert len(store.rows) == 0

    inserted = seed_demo_records_if_empty(repo, enabled=True)
    assert inserted == 38
    assert len(store.rows) == 38
    assert sum(1 for r in store.rows if r["parking_status"] == "IN_PARKING") == 6

    # Second run is idempotent
    assert seed_demo_records_if_empty(repo, enabled=True) == 0
    assert len(store.rows) == 38

    # initialize runs DDL + seeder + warm_mirror.load_from_cursor on a single connection
    fake_mirror = mock.MagicMock()
    seeder_calls: list[ParkingRepository] = []
    with mock.patch("src.backend.storage.repository.ensure_mysql_table") as mock_ddl:
        repo.initialize(
            warm_mirror=fake_mirror,
            seeder=lambda r: seeder_calls.append(r),
        )
    mock_ddl.assert_called_once()
    assert seeder_calls == [repo]
    fake_mirror.load_from_cursor.assert_called_once()
