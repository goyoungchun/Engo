"""SQLite schema and connection handling.

Design notes (why the schema looks like this):

The app is local-only, but study data must be movable between machines and
merged without a server. So every synced row carries the four columns a
last-writer-wins merge needs:

    id          TEXT  UUID4 hex, generated on the device that created the row.
                      Never an autoincrement integer -- two devices would both
                      hand out id 7 to different rows and the merge would be
                      ambiguous.
    updated_at  INTEGER  epoch milliseconds UTC, bumped on every write.
    deleted     INTEGER  tombstone flag. Rows are never physically removed,
                      otherwise a delete on device A would be silently undone
                      by the next import from device B.
    origin      TEXT  device id of the last writer. Used only to break
                      updated_at ties so the merge is deterministic and
                      order-independent.

Local-only state (device id, window geometry, UI preferences) lives in tables
that the exporter ignores -- see sync.SYNCED_TABLES.
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from pathlib import Path

SCHEMA_VERSION = 1

# Columns every synced table shares. Kept as one string so the definitions
# below stay readable and can't drift apart.
_SYNC_COLUMNS = """
    id          TEXT    PRIMARY KEY,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    deleted     INTEGER NOT NULL DEFAULT 0,
    origin      TEXT    NOT NULL
"""

_SCHEMA = f"""
-- 1. 영어 표현 정리
CREATE TABLE IF NOT EXISTS expressions (
    {_SYNC_COLUMNS},
    english          TEXT NOT NULL DEFAULT '',
    korean           TEXT NOT NULL DEFAULT '',
    note             TEXT NOT NULL DEFAULT '',
    tags             TEXT NOT NULL DEFAULT '',
    source           TEXT NOT NULL DEFAULT '',
    studied_on       TEXT NOT NULL DEFAULT '',   -- 'YYYY-MM-DD', 복습 메모지가 날짜로 묶는 기준
    box              INTEGER NOT NULL DEFAULT 0, -- Leitner 단계
    review_count     INTEGER NOT NULL DEFAULT 0,
    last_reviewed_at INTEGER NOT NULL DEFAULT 0
);

-- 4. 외우고 싶은 문장 정리
CREATE TABLE IF NOT EXISTS sentences (
    {_SYNC_COLUMNS},
    english          TEXT NOT NULL DEFAULT '',
    korean           TEXT NOT NULL DEFAULT '',
    note             TEXT NOT NULL DEFAULT '',
    tags             TEXT NOT NULL DEFAULT '',
    source           TEXT NOT NULL DEFAULT '',
    studied_on       TEXT NOT NULL DEFAULT '',
    starred          INTEGER NOT NULL DEFAULT 0,
    box              INTEGER NOT NULL DEFAULT 0,
    review_count     INTEGER NOT NULL DEFAULT 0,
    last_reviewed_at INTEGER NOT NULL DEFAULT 0
);

-- 5. 문법 정리
CREATE TABLE IF NOT EXISTS grammar (
    {_SYNC_COLUMNS},
    title       TEXT NOT NULL DEFAULT '',  -- 주요 표현
    body        TEXT NOT NULL DEFAULT '',  -- 설명
    examples    TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',
    studied_on  TEXT NOT NULL DEFAULT ''
);

-- 3. 영어 원문 해석 해보기 (지문)
CREATE TABLE IF NOT EXISTS passages (
    {_SYNC_COLUMNS},
    title      TEXT NOT NULL DEFAULT '',
    raw_text   TEXT NOT NULL DEFAULT '',
    tags       TEXT NOT NULL DEFAULT '',
    studied_on TEXT NOT NULL DEFAULT ''
);

-- 3. 지문의 문장별 행. 행 단위로 병합되므로 두 기기에서 서로 다른
--    문장을 해석했다면 양쪽 해석이 모두 살아남는다.
CREATE TABLE IF NOT EXISTS passage_lines (
    {_SYNC_COLUMNS},
    passage_id  TEXT NOT NULL,
    seq         INTEGER NOT NULL DEFAULT 0,
    english     TEXT NOT NULL DEFAULT '',
    translation TEXT NOT NULL DEFAULT '',   -- 사용자가 직접 해본 해석
    note        TEXT NOT NULL DEFAULT ''    -- 스스로에게 남기는 피드백
);

-- 로컬 전용: 내보내기에 포함되지 않는다.
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 로컬 전용: 스티키 메모 창의 위치/크기/옵션. 기기마다 화면이 다르므로
-- 동기화하면 오히려 창이 화면 밖으로 나간다.
CREATE TABLE IF NOT EXISTS sticky_windows (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL DEFAULT 'expressions',
    query      TEXT NOT NULL DEFAULT '',
    x          INTEGER NOT NULL DEFAULT 100,
    y          INTEGER NOT NULL DEFAULT 100,
    w          INTEGER NOT NULL DEFAULT 320,
    h          INTEGER NOT NULL DEFAULT 380,
    hide_answer INTEGER NOT NULL DEFAULT 1,
    on_top     INTEGER NOT NULL DEFAULT 0,
    opacity    INTEGER NOT NULL DEFAULT 100,
    color      TEXT NOT NULL DEFAULT 'yellow',
    open       INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_expr_live    ON expressions(deleted, studied_on);
CREATE INDEX IF NOT EXISTS ix_expr_updated ON expressions(updated_at);
CREATE INDEX IF NOT EXISTS ix_sent_live    ON sentences(deleted, studied_on);
CREATE INDEX IF NOT EXISTS ix_sent_updated ON sentences(updated_at);
CREATE INDEX IF NOT EXISTS ix_gram_live    ON grammar(deleted, title);
CREATE INDEX IF NOT EXISTS ix_gram_updated ON grammar(updated_at);
CREATE INDEX IF NOT EXISTS ix_pass_live    ON passages(deleted, updated_at);
CREATE INDEX IF NOT EXISTS ix_line_passage ON passage_lines(passage_id, seq);
CREATE INDEX IF NOT EXISTS ix_line_updated ON passage_lines(updated_at);
"""


# Highest updated_at this database has ever seen -- local or imported.
# Guarded by the GIL-atomicity of int assignment plus GUI-thread-only writes.
_clock_floor = 0


def now_ms() -> int:
    """Epoch milliseconds, made monotone against everything already seen.

    Plain wall time is not enough for last-writer-wins: if another device's
    clock runs fast, every row it exports carries a future timestamp, and
    edits made *afterwards* on a correct clock would silently lose the merge
    until real time catches up. Taking max(wall, seen+1) — a Lamport clock
    floored to wall time — guarantees that a local edit always outranks any
    row this database has already merged, whatever the clocks did.
    """
    global _clock_floor
    stamp = max(int(time.time() * 1000), _clock_floor + 1)
    _clock_floor = stamp
    return stamp


def observe_timestamp(ms: int) -> None:
    """Feed an imported row's updated_at into the clock floor."""
    global _clock_floor
    if ms > _clock_floor:
        _clock_floor = ms


class transaction:
    """`with db.transaction():` -- BEGIN/COMMIT with rollback on error.

    With isolation_level=None only single statements are atomic; every
    multi-statement write path must run inside one of these, or a crash can
    leave it half-applied. Nested use is a no-op (SQLite has no nested BEGIN).
    """

    def __enter__(self):
        conn = connect()
        self._own = not conn.in_transaction
        if self._own:
            conn.execute("BEGIN")
        return conn

    def __exit__(self, exc_type, exc, tb):
        conn = connect()
        if self._own and conn.in_transaction:
            conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


def new_id() -> str:
    return uuid.uuid4().hex


def default_data_dir() -> Path:
    # STUDYENGLISH_HOME is the old name, still honoured so an existing setup
    # (and the test suite) keeps working after the rename to Engo.
    base = os.environ.get("ENGO_HOME") or os.environ.get("STUDYENGLISH_HOME")
    if base:
        return Path(base)

    appdata = Path(os.environ.get("APPDATA", Path.home()))
    new = appdata / "Engo"
    old = appdata / "StudyEnglish"
    if not new.exists() and old.exists():
        # One-time move of the pre-rename data. A rename on the same volume is
        # atomic, so this cannot leave the study data half-copied.
        try:
            old.rename(new)
        except OSError:
            return old          # in use or across volumes: keep using it
    return new


def db_path() -> Path:
    return default_data_dir() / "study.db"


_conn: sqlite3.Connection | None = None


def connect() -> sqlite3.Connection:
    """Open (once) the process-wide connection.

    One connection for the whole process: sticky note windows live in the same
    process as the main window, so there is nothing to share across threads and
    a connection pool would only add memory.
    """
    global _conn
    if _conn is not None:
        return _conn

    if _sealed:
        # Uninstall deleted the data folder. Things still shutting down --
        # sticky notes saving their position, most of all -- would otherwise
        # recreate it on the way out. Give them a scratch database that dies
        # with the process instead of resurrecting what the user just erased.
        path = ":memory:"
    else:
        path = db_path()
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Cap SQLite's page cache at ~2MB instead of the default 2MB-and-growing
    # heuristic, and let it release freed heap back to the OS. This matters
    # because the app is expected to sit in the tray all day.
    conn.execute("PRAGMA cache_size=-2000")
    conn.executescript(_SCHEMA)

    _set_meta_default(conn, "schema_version", str(SCHEMA_VERSION))
    _set_meta_default(conn, "device_id", uuid.uuid4().hex[:12])
    _set_meta_default(conn, "device_name", os.environ.get("COMPUTERNAME", "PC"))

    # Seed the merge clock with the newest stamp already in this database, so
    # monotonicity survives restarts (see now_ms).
    global _clock_floor
    for table in ("expressions", "sentences", "grammar",
                  "passages", "passage_lines"):
        row = conn.execute(f"SELECT MAX(updated_at) AS m FROM {table}").fetchone()
        if row["m"] and row["m"] > _clock_floor:
            _clock_floor = row["m"]

    _conn = conn
    return conn


def _set_meta_default(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR IGNORE INTO app_meta(key, value) VALUES (?, ?)", (key, value))


def get_meta(key: str, default: str = "") -> str:
    row = connect().execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    connect().execute(
        "INSERT INTO app_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def device_id() -> str:
    return get_meta("device_id")


def close() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


_sealed = False


def seal() -> None:
    """Never touch the data folder again -- uninstall has removed it."""
    global _sealed
    _sealed = True
    close()
