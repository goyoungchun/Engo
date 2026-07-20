"""Export / import / merge.

There is no server. Moving data between machines means writing a file on one
device and reading it on another, possibly in both directions, possibly more
than once, possibly out of order. So the merge is built to be:

  * idempotent   -- importing the same file twice changes nothing the second time
  * commutative  -- A-then-B and B-then-A reach the same state
  * total        -- every row is resolved; no "conflict" state to babysit

That is achieved with last-writer-wins per row, keyed on (updated_at, origin).
`origin` only breaks exact-millisecond ties, but it makes the outcome
deterministic instead of dependent on import order.

Deletes propagate because deleted rows are tombstones (deleted = 1) that carry
an updated_at like any other write -- a delete at t=5 beats an edit at t=3, and
an edit at t=7 resurrects a row deleted at t=5. That is the intended behaviour:
the most recent human action wins.
"""

from __future__ import annotations

import csv
import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import db, repo

# Kept at the pre-rename value on purpose: it is the identifier written into
# every .seb file, and changing it would make the program reject exports the
# user already has.
FORMAT = "studyenglish-export"
FORMAT_VERSION = 1

# Tables carried in an export. Deliberately excludes app_meta and
# sticky_windows: device id and window geometry are per-machine, and importing
# them would clone the source device's identity or push notes off-screen.
SYNCED_TABLES = ("expressions", "sentences", "grammar", "passages", "passage_lines")

SYNC_META = ("id", "created_at", "updated_at", "deleted", "origin")


@dataclass
class MergeReport:
    added: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    deleted_applied: int = 0
    source_device: str = ""
    exported_at: int = 0

    @property
    def total_added(self) -> int:
        return sum(self.added.values())

    @property
    def total_updated(self) -> int:
        return sum(self.updated.values())

    @property
    def total_skipped(self) -> int:
        return sum(self.skipped.values())

    def summary(self) -> str:
        from .i18n import t
        lines = [
            t("rp_from", device=self.source_device or t("rp_unknown")),
            t("rp_added", n=self.total_added),
            t("rp_updated", n=self.total_updated),
            t("rp_skipped", n=self.total_skipped),
        ]
        if self.deleted_applied:
            lines.append(t("rp_deleted", n=self.deleted_applied))
        detail = [
            f"  · {t}: +{self.added.get(t, 0)} / ~{self.updated.get(t, 0)}"
            for t in SYNCED_TABLES
            if self.added.get(t) or self.updated.get(t)
        ]
        if detail:
            lines.append("")
            lines.extend(detail)
        return "\n".join(lines)


def _table_columns(table: str) -> tuple[str, ...]:
    return SYNC_META + repo.EDITABLE[table]


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------

def export_to_file(path: str | Path, since_ms: int = 0,
                   include_deleted: bool = True) -> dict[str, int]:
    """Write a merge-ready snapshot.

    `since_ms > 0` produces an incremental export (only rows touched since
    that timestamp) -- much smaller for routine back-and-forth, and still
    correct to merge because every row carries its own timestamp.

    Files ending in .gz (or the default .seb) are gzipped; a plain .json is
    written uncompressed so it stays diffable and hand-inspectable.
    """
    path = Path(path)
    conn = db.connect()
    payload: dict[str, Any] = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "schema_version": db.SCHEMA_VERSION,
        "exported_at": db.now_ms(),
        "since": since_ms,
        "device_id": db.device_id(),
        "device_name": db.get_meta("device_name"),
        "tables": {},
    }

    counts: dict[str, int] = {}
    for table in SYNCED_TABLES:
        cols = _table_columns(table)
        sql = f"SELECT {', '.join(cols)} FROM {table} WHERE updated_at >= ?"
        if not include_deleted:
            sql += " AND deleted = 0"
        rows = [list(r) for r in conn.execute(sql, (since_ms,))]
        payload["tables"][table] = {"columns": list(cols), "rows": rows}
        counts[table] = len(rows)

    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if path.suffix.lower() in (".json", ".txt"):
        path.write_text(text, encoding="utf-8")
    else:
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as fh:
            fh.write(text)
    return counts


def _read_payload(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":                      # gzip magic
        text = gzip.decompress(raw).decode("utf-8")
    else:
        text = raw.decode("utf-8-sig")
    payload = json.loads(text)
    if payload.get("format") != FORMAT:
        raise ValueError("이 파일은 Engo 내보내기 파일이 아닙니다.")
    if payload.get("format_version", 0) > FORMAT_VERSION:
        raise ValueError(
            "더 새로운 버전에서 만든 파일입니다. 프로그램을 먼저 업데이트하세요."
        )
    return payload


def preview_file(path: str | Path) -> dict[str, Any]:
    """Read an export's header + row counts without touching the database."""
    payload = _read_payload(Path(path))
    return {
        "device_name": payload.get("device_name", ""),
        "device_id": payload.get("device_id", ""),
        "exported_at": payload.get("exported_at", 0),
        "incremental": bool(payload.get("since")),
        "counts": {t: len(payload["tables"].get(t, {}).get("rows", []))
                   for t in SYNCED_TABLES if t in payload.get("tables", {})},
    }


# --------------------------------------------------------------------------
# import / merge
# --------------------------------------------------------------------------

def _wins(incoming_ts: int, incoming_origin: str,
          local_ts: int, local_origin: str) -> bool:
    """Last-writer-wins with a deterministic tie-break."""
    if incoming_ts != local_ts:
        return incoming_ts > local_ts
    return incoming_origin > local_origin


def import_file(path: str | Path, dry_run: bool = False) -> MergeReport:
    payload = _read_payload(Path(path))
    return merge_payload(payload, dry_run=dry_run)


def merge_payload(payload: dict[str, Any], dry_run: bool = False) -> MergeReport:
    conn = db.connect()
    report = MergeReport(
        source_device=payload.get("device_name") or payload.get("device_id", ""),
        exported_at=payload.get("exported_at", 0),
    )

    conn.execute("BEGIN")
    try:
        for table in SYNCED_TABLES:
            block = payload.get("tables", {}).get(table)
            if not block:
                continue
            added, updated, skipped, deletes = _merge_table(conn, table, block)
            report.added[table] = added
            report.updated[table] = updated
            report.skipped[table] = skipped
            report.deleted_applied += deletes
        if dry_run:
            conn.execute("ROLLBACK")
        else:
            conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    if not dry_run:
        _drop_orphan_lines(conn)
    return report


def _merge_table(conn, table: str, block: dict[str, Any]) -> tuple[int, int, int, int]:
    incoming_cols: list[str] = block["columns"]
    known = set(_table_columns(table))
    # Tolerate a file from a slightly different version: unknown columns are
    # dropped, missing ones fall back to the local/default value.
    usable = [c for c in incoming_cols if c in known]
    idx = {c: incoming_cols.index(c) for c in usable}
    if "id" not in idx or "updated_at" not in idx:
        return 0, 0, 0, 0

    local = {
        r["id"]: (r["updated_at"], r["origin"], r["deleted"])
        for r in conn.execute(f"SELECT id, updated_at, origin, deleted FROM {table}")
    }

    write_cols = [c for c in usable if c != "id"]
    insert_sql = (
        f"INSERT INTO {table} (id, {', '.join(write_cols)}) "
        f"VALUES ({', '.join('?' * (len(write_cols) + 1))})"
    )
    update_sql = (
        f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in write_cols)} WHERE id = ?"
    )

    added = updated = skipped = deletes = 0
    inserts: list[tuple] = []
    updates: list[tuple] = []

    for row in block["rows"]:
        row_id = row[idx["id"]]
        ts = row[idx["updated_at"]]
        origin = row[idx["origin"]] if "origin" in idx else ""
        values = [row[idx[c]] for c in write_cols]

        cur = local.get(row_id)
        if cur is None:
            inserts.append((row_id, *values))
            added += 1
            if "deleted" in idx and row[idx["deleted"]]:
                deletes += 1
        elif _wins(ts, origin, cur[0], cur[1]):
            updates.append((*values, row_id))
            updated += 1
            if "deleted" in idx and row[idx["deleted"]] and not cur[2]:
                deletes += 1
        else:
            skipped += 1

    if inserts:
        conn.executemany(insert_sql, inserts)
    if updates:
        conn.executemany(update_sql, updates)
    return added, updated, skipped, deletes


def _drop_orphan_lines(conn) -> None:
    """Tombstone passage_lines whose passage never arrived.

    Happens when someone hand-edits an export or merges a partial file. Left
    alone they would be invisible rows padding the database forever.
    """
    conn.execute(
        "UPDATE passage_lines SET deleted = 1, updated_at = ?, origin = ? "
        "WHERE deleted = 0 AND passage_id NOT IN (SELECT id FROM passages)",
        (db.now_ms(), db.device_id()),
    )


# --------------------------------------------------------------------------
# CSV (for spreadsheets / Anki, one table at a time)
# --------------------------------------------------------------------------

CSV_FIELDS = {
    "expressions": ("english", "korean", "note", "tags", "source", "studied_on"),
    "sentences": ("english", "korean", "note", "tags", "source", "studied_on"),
    "grammar": ("title", "body", "examples", "tags", "studied_on"),
}


def export_csv(table: str, path: str | Path) -> int:
    fields = CSV_FIELDS[table]
    rows = db.connect().execute(
        f"SELECT {', '.join(fields)} FROM {table} WHERE deleted = 0 "
        f"ORDER BY studied_on DESC, created_at DESC"
    )
    # utf-8-sig so Excel on Windows opens Korean text correctly.
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(fields)
        n = 0
        for r in rows:
            writer.writerow([r[f] for f in fields])
            n += 1
    return n


def import_csv(table: str, path: str | Path) -> int:
    """Append rows from a CSV. Always adds -- CSV has no ids, so this cannot
    merge; it is an intake path for material typed up elsewhere."""
    fields = CSV_FIELDS[table]
    n = 0
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return 0
        header = {(h or "").strip().lower(): h for h in reader.fieldnames}
        conn = db.connect()
        conn.execute("BEGIN")
        try:
            for raw in reader:
                values = {f: (raw.get(header.get(f, ""), "") or "").strip()
                          for f in fields}
                if not any(values.get(k) for k in ("english", "korean", "title", "body")):
                    continue
                values.setdefault("studied_on", "")
                if not values["studied_on"]:
                    values["studied_on"] = repo.today()
                repo.save_row(table, values)
                n += 1
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return n


def backup_database(dest: str | Path) -> Path:
    """Byte-for-byte copy of the live database, WAL included.

    Uses SQLite's own backup API rather than copying the file so it is safe
    while the app is running.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3
    target = sqlite3.connect(dest)
    try:
        db.connect().backup(target)
    finally:
        target.close()
    return dest

