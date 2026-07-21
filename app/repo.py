"""CRUD layer.

Everything the UI does to synced data goes through `save_row` / `soft_delete`
so the merge bookkeeping (updated_at, origin, tombstone) can never be
forgotten at a call site.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Iterable, Sequence

from . import db

# Columns the UI is allowed to write, per table. Anything not listed here
# (id, created_at, updated_at, deleted, origin) is managed by this module.
EDITABLE: dict[str, tuple[str, ...]] = {
    "expressions": (
        "english", "korean", "note", "tags", "source", "studied_on",
        "box", "review_count", "last_reviewed_at",
    ),
    "sentences": (
        "english", "korean", "note", "tags", "source", "studied_on", "starred",
        "box", "review_count", "last_reviewed_at",
    ),
    "grammar": ("title", "body", "examples", "tags", "studied_on"),
    "passages": ("title", "raw_text", "tags", "studied_on", "source_url"),
    "passage_lines": ("passage_id", "seq", "english", "translation", "note"),
}


def today() -> str:
    return _dt.date.today().isoformat()


# --------------------------------------------------------------------------
# generic write path
# --------------------------------------------------------------------------

def save_row(table: str, values: dict[str, Any], row_id: str | None = None) -> str:
    """Insert or update one row, stamping the merge metadata.

    Returns the row id. Unknown keys in `values` are ignored rather than
    raising, so a UI form can pass its whole field dict.
    """
    cols = EDITABLE[table]
    data = {k: v for k, v in values.items() if k in cols}
    conn = db.connect()
    ts = db.now_ms()
    origin = db.device_id()

    if row_id:
        if not data:
            return row_id
        assigns = ", ".join(f"{c} = ?" for c in data)
        conn.execute(
            f"UPDATE {table} SET {assigns}, updated_at = ?, origin = ?, deleted = 0 "
            f"WHERE id = ?",
            (*data.values(), ts, origin, row_id),
        )
        return row_id

    row_id = db.new_id()
    names = ["id", "created_at", "updated_at", "deleted", "origin", *data.keys()]
    conn.execute(
        f"INSERT INTO {table} ({', '.join(names)}) "
        f"VALUES ({', '.join('?' * len(names))})",
        (row_id, ts, ts, 0, origin, *data.values()),
    )
    return row_id


def soft_delete(table: str, row_ids: Sequence[str]) -> None:
    """Tombstone rows. Never a hard DELETE -- see db.py header.

    One transaction, so deleting a passage can never leave its lines live
    after a crash; chunked, so a huge selection cannot exceed SQLite's bound
    parameter limit.
    """
    if not row_ids:
        return
    with db.transaction() as conn:
        for start in range(0, len(row_ids), 500):
            chunk = list(row_ids[start:start + 500])
            marks = ", ".join("?" * len(chunk))
            conn.execute(
                f"UPDATE {table} SET deleted = 1, updated_at = ?, origin = ? "
                f"WHERE id IN ({marks})",
                (db.now_ms(), db.device_id(), *chunk),
            )
            if table == "passages":
                conn.execute(
                    f"UPDATE passage_lines SET deleted = 1, updated_at = ?, "
                    f"origin = ? WHERE passage_id IN ({marks})",
                    (db.now_ms(), db.device_id(), *chunk),
                )


def get_row(table: str, row_id: str) -> dict[str, Any] | None:
    row = db.connect().execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return dict(row) if row else None


def purge_tombstones(older_than_days: int = 180) -> int:
    """Physically drop long-dead tombstones.

    Safe only once every device has certainly seen the deletion, hence the
    generous default. Keeps the file from growing forever.
    """
    cutoff = db.now_ms() - older_than_days * 86_400_000
    total = 0
    with db.transaction() as conn:
        for table in EDITABLE:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE deleted = 1 AND updated_at < ?",
                (cutoff,),
            )
            total += cur.rowcount or 0
    # VACUUM cannot run inside a transaction.
    db.connect().execute("VACUUM")
    return total


# --------------------------------------------------------------------------
# queries
# --------------------------------------------------------------------------

def _search_clause(fields: Iterable[str], term: str) -> tuple[str, list[Any]]:
    term = term.strip()
    if not term:
        return "", []
    ors = " OR ".join(f"{f} LIKE ?" for f in fields)
    return f" AND ({ors})", [f"%{term}%"] * len(tuple(fields))


SEARCH_FIELDS = {
    "expressions": ("english", "korean", "note", "tags", "source"),
    "sentences": ("english", "korean", "note", "tags", "source"),
    "grammar": ("title", "body", "examples", "tags"),
    "passages": ("title", "raw_text", "tags"),
}

# Columns each list view actually renders. `note`-style long text is truncated
# in SQL so scrolling a few thousand rows never pulls whole essays into memory;
# the editor re-reads the full row by id when a row is selected.
LIST_COLUMNS = {
    "expressions": "id, english, korean, substr(note, 1, 120) AS note, tags, studied_on, box",
    "sentences": "id, english, korean, substr(note, 1, 120) AS note, tags, studied_on, starred, box",
    "grammar": "id, title, substr(body, 1, 160) AS body, tags, studied_on",
    # line_count excludes section headings (english starting with "## "), so
    # the list's "N sentences" matches the numbered rows the passage shows.
    "passages": ("id, title, tags, studied_on, updated_at, "
                 "(SELECT COUNT(*) FROM passage_lines l "
                 " WHERE l.passage_id = passages.id AND l.deleted = 0 "
                 "   AND l.english NOT LIKE '## %') AS line_count, "
                 "(SELECT COUNT(*) FROM passage_lines l "
                 " WHERE l.passage_id = passages.id AND l.deleted = 0 "
                 "   AND l.english NOT LIKE '## %' "
                 "   AND TRIM(l.translation) <> '') AS done_count"),
}

ORDER_BY = {
    "expressions": "studied_on DESC, created_at DESC",
    "sentences": "starred DESC, studied_on DESC, created_at DESC",
    "grammar": "studied_on DESC, created_at DESC",
    "passages": "updated_at DESC",
}


def list_rows(
    table: str,
    search: str = "",
    tag: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sql = f"SELECT {LIST_COLUMNS[table]} FROM {table} WHERE deleted = 0"
    params: list[Any] = []

    fields = SEARCH_FIELDS[table]
    clause, extra = _search_clause(fields, search)
    sql += clause
    params += extra

    if tag:
        sql += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    if date_from and table != "passages":
        sql += " AND studied_on >= ?"
        params.append(date_from)
    if date_to and table != "passages":
        sql += " AND studied_on <= ?"
        params.append(date_to)

    sql += f" ORDER BY {ORDER_BY[table]} LIMIT ? OFFSET ?"
    params += [limit, offset]
    return [dict(r) for r in db.connect().execute(sql, params)]


def count_rows(table: str, search: str = "", tag: str = "",
               date_from: str = "", date_to: str = "") -> int:
    sql = f"SELECT COUNT(*) AS n FROM {table} WHERE deleted = 0"
    params: list[Any] = []
    clause, extra = _search_clause(SEARCH_FIELDS[table], search)
    sql += clause
    params += extra
    if tag:
        sql += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    if date_from and table != "passages":
        sql += " AND studied_on >= ?"
        params.append(date_from)
    if date_to and table != "passages":
        sql += " AND studied_on <= ?"
        params.append(date_to)
    return db.connect().execute(sql, params).fetchone()["n"]


def all_sources(table: str) -> list[str]:
    """Distinct non-empty sources, for the source-field autocomplete.

    Grammar has no source column, so it simply has nothing to offer here.
    """
    if table not in ("expressions", "sentences"):
        return []
    rows = db.connect().execute(
        f"SELECT DISTINCT source FROM {table} "
        f"WHERE deleted = 0 AND source <> '' ORDER BY source"
    )
    return [r["source"] for r in rows]


def all_tags(table: str) -> list[str]:
    rows = db.connect().execute(
        f"SELECT DISTINCT tags FROM {table} WHERE deleted = 0 AND tags <> ''"
    )
    seen: set[str] = set()
    for r in rows:
        for t in r["tags"].split(","):
            t = t.strip()
            if t:
                seen.add(t)
    return sorted(seen)


def study_dates(table: str, limit: int = 60) -> list[tuple[str, int]]:
    """Distinct 학습 날짜 + 건수, 최신순. 복습 메모지의 날짜 선택에 쓴다."""
    rows = db.connect().execute(
        f"SELECT studied_on, COUNT(*) AS n FROM {table} "
        f"WHERE deleted = 0 AND studied_on <> '' "
        f"GROUP BY studied_on ORDER BY studied_on DESC LIMIT ?",
        (limit,),
    )
    return [(r["studied_on"], r["n"]) for r in rows]


# --------------------------------------------------------------------------
# passages (3. 영어 원문 해석 해보기)
# --------------------------------------------------------------------------

# Titles are always followed by a name, so a period after one is never the end
# of a sentence.
# Titles and name particles that always precede a proper noun, so the period
# is never a sentence end -- "U.S. Rep. Alexandria Ocasio-Cortez" is one
# sentence. Kept broad because news writing is full of them.
_TITLE_ABBREV = (
    # honorifics
    "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Rev.", "Fr.", "Br.", "Msgr.",
    "Hon.", "Sir.", "St.",
    # political / official
    "Rep.", "Reps.", "Sen.", "Sens.", "Gov.", "Govs.", "Pres.", "Sec.",
    "Amb.", "Supt.", "Det.", "Ofc.",
    # military ranks
    "Gen.", "Lt.", "Col.", "Sgt.", "Capt.", "Maj.", "Adm.", "Cmdr.", "Brig.",
    "Pvt.", "Cpl.", "Cmdr.",
    # name suffixes and places
    "Jr.", "Sr.", "Esq.", "Mt.", "Ft.")

# These can legitimately end a sentence ("...arrived at 9 a.m. He said..."), so
# they only suppress the split when what follows is not a new sentence -- i.e.
# not whitespace followed by a capital letter.
_SOFT_ABBREV = ("vs.", "etc.", "e.g.", "i.e.", "a.m.", "p.m.",
                "Inc.", "Ltd.", "No.", "Fig.")

# An all-caps dotted initialism: U.S., U.K., U.N., E.U., U.S.A. Two or more
# single-capital-and-dot pairs at the end of the last word.
_INITIALISM = re.compile(r"(?:[A-Z]\.){2,}$")


def _is_abbreviation(buf: str, rest: str) -> bool:
    """True if the period just consumed belongs to an abbreviation, not a stop."""
    tail = buf.rstrip()
    if any(tail.endswith(a) for a in _TITLE_ABBREV):
        return True
    # A country/organisation initialism is part of a name far more often than
    # it ends a sentence -- even before a capital word -- so it never breaks:
    # "the U.S. Bureau of Labor Statistics" is one sentence, not two. Lower-case
    # dotted abbreviations (a.m.) stay soft below, so "at 9 a.m. He left" still
    # splits.
    last = tail.split()[-1] if tail.split() else tail
    if _INITIALISM.search(last):
        return True
    if any(tail.endswith(a) for a in _SOFT_ABBREV):
        nxt = rest.lstrip()
        return not (nxt[:1].isupper() or nxt == "")
    return False


def split_sentences(text: str) -> list[str]:
    """Split a passage into sentences, one per grid row.

    Deliberately a small hand-rolled splitter rather than an NLP dependency:
    it must run instantly, add no memory, and the user can always fix a bad
    split by editing the row.
    """
    out: list[str] = []
    for block in text.replace("\r\n", "\n").split("\n"):
        block = block.strip()
        if not block:
            continue
        buf = ""
        i = 0
        in_quote = False       # inside "..." a full stop is not a sentence end
        while i < len(block):
            ch = block[i]
            buf += ch
            # Track double-quote spans. A quote can hold several sentences --
            # '"You hissed the lecture. You tasted the whole worm!"' -- and the
            # reader wants the quotation kept whole, so punctuation inside it
            # does not break. Curly quotes are directional; a straight " toggles.
            closed = False
            if ch == "“":
                in_quote = True
            elif ch == "”":
                in_quote, closed = False, True
            elif ch == '"':
                closed = in_quote
                in_quote = not in_quote
            # When a quotation closes a sentence -- punctuation right before the
            # closing quote, a capital or the end just after it -- the sentence
            # ends there: '..."Goodbye now." Then he left.' is two sentences.
            if closed and len(buf) >= 2 and buf[-2] in ".!?":
                rest = block[i + 1:].lstrip()
                if rest == "" or rest[:1].isupper():
                    out.append(buf.strip())
                    buf = ""
                    i += 1
                    continue
            if ch in ".!?" and not in_quote:
                # don't break inside "Mr." / "e.g." / decimals like 3.5
                if ch == "." and i + 1 < len(block) and block[i + 1].isdigit():
                    i += 1
                    continue
                if ch == "." and _is_abbreviation(buf, block[i + 1:]):
                    i += 1
                    continue
                # swallow trailing quotes/brackets that belong to this sentence
                j = i + 1
                while j < len(block) and block[j] in '"\')]}»”’':
                    buf += block[j]
                    j += 1
                i = j
                if i >= len(block) or block[i] == " ":
                    out.append(buf.strip())
                    buf = ""
                continue
            i += 1
        if buf.strip():
            out.append(buf.strip())
    return _merge_short(_group_speaker_turns(out))


# A speaker label in an interview transcript: an all-caps name, an optional
# role after a comma, then a colon -- "AYESHA RASCOE, HOST:", "RASCOE:".
_SPEAKER = re.compile(
    r"^[A-Z][A-Z'’.\-]+(?: [A-Z][A-Z'’.\-]+)*(?:, [A-Z][A-Za-z ]+)?:\s")


def _is_heading(sentence: str) -> bool:
    return sentence.startswith("## ")


def _group_speaker_turns(sentences: list[str]) -> list[str]:
    """In a transcript, keep each person's turn as one row.

    The period-heavy back-and-forth of an interview ("RASCOE: All right. Tell
    us more.") otherwise splits into a sentence per clause. When several
    speaker labels are present the text is treated as a transcript: everything
    from one label up to the next becomes a single row. Headings stay on their
    own. Non-transcript prose has no labels and is left untouched.
    """
    if sum(1 for s in sentences if _SPEAKER.match(s)) < 3:
        return sentences
    grouped: list[str] = []
    in_turn = False
    for sentence in sentences:
        if _is_heading(sentence):
            grouped.append(sentence)
            in_turn = False
        elif _SPEAKER.match(sentence):
            grouped.append(sentence)
            in_turn = True
        elif in_turn:
            grouped[-1] = f"{grouped[-1]} {sentence}"
        else:
            grouped.append(sentence)
    return grouped


def _merge_short(sentences: list[str]) -> list[str]:
    """Fold a stray one-word sentence ("Welcome.", "Yes.") into the one before.

    A single word marooned as its own row reads as a mistake. Headings and the
    first row are left alone; everything else joins the previous row.
    """
    out: list[str] = []
    for sentence in sentences:
        word = sentence.rstrip(".!?\"')]}»”’").strip()
        if out and not _is_heading(sentence) and not _is_heading(out[-1]) \
                and word and " " not in word:
            out[-1] = f"{out[-1]} {sentence}"
        else:
            out.append(sentence)
    return out


def create_passage(title: str, raw_text: str, tags: str = "",
                   source_url: str = "") -> str:
    # One transaction: a crash must not leave a passage with half its lines.
    with db.transaction():
        passage_id = save_row("passages", {
            "title": title or "제목 없음",
            "raw_text": raw_text,
            "tags": tags,
            "studied_on": today(),
            "source_url": source_url,
        })
        for seq, sentence in enumerate(split_sentences(raw_text)):
            save_row("passage_lines", {
                "passage_id": passage_id, "seq": seq, "english": sentence,
            })
    return passage_id


def seen_article_guids() -> set[str]:
    """Guids of articles already brought in, so nothing is imported twice."""
    rows = db.connect().execute("SELECT guid FROM seen_articles")
    return {r["guid"] for r in rows}


def mark_articles_seen(guids: list[str]) -> None:
    if not guids:
        return
    now = db.now_ms()
    with db.transaction() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO seen_articles(guid, imported_at) VALUES (?, ?)",
            [(g, now) for g in guids],
        )


def passage_lines(passage_id: str) -> list[dict[str, Any]]:
    rows = db.connect().execute(
        "SELECT id, seq, english, translation, note FROM passage_lines "
        "WHERE passage_id = ? AND deleted = 0 ORDER BY seq",
        (passage_id,),
    )
    return [dict(r) for r in rows]


def resplit_passage(passage_id: str, raw_text: str) -> None:
    """Re-split a passage, preserving translations for unchanged sentences.

    Matching is by exact sentence text: if the user fixes a typo in one
    sentence, that row's translation is lost but every other row survives.
    """
    existing = passage_lines(passage_id)
    by_text: dict[str, dict[str, Any]] = {}
    for row in existing:
        by_text.setdefault(row["english"].strip(), row)

    # One transaction: without it, a crash between the tombstoning and the
    # re-insert loop would leave every translation deleted.
    with db.transaction():
        soft_delete("passage_lines", [r["id"] for r in existing])
        for seq, sentence in enumerate(split_sentences(raw_text)):
            old = by_text.get(sentence.strip())
            if old:
                save_row("passage_lines", {
                    "passage_id": passage_id, "seq": seq, "english": sentence,
                    "translation": old["translation"], "note": old["note"],
                }, row_id=old["id"])
            else:
                save_row("passage_lines", {
                    "passage_id": passage_id, "seq": seq, "english": sentence,
                })
        save_row("passages", {"raw_text": raw_text}, row_id=passage_id)


# --------------------------------------------------------------------------
# review (2. 복습 메모지)
# --------------------------------------------------------------------------

def review_items(kind: str, studied_on: str = "", tag: str = "",
                 only_weak: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    """Rows for a sticky note. `kind` is 'expressions' or 'sentences'."""
    sql = (f"SELECT id, english, korean, box FROM {kind} WHERE deleted = 0 "
           f"AND (english <> '' OR korean <> '')")
    params: list[Any] = []
    if studied_on:
        sql += " AND studied_on = ?"
        params.append(studied_on)
    if tag:
        sql += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    if only_weak:
        sql += " AND box <= 1"
    sql += " ORDER BY box ASC, studied_on DESC, created_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.connect().execute(sql, params)]


def mark_reviewed(table: str, row_id: str, correct: bool) -> None:
    """Leitner-style: right answer promotes a box, wrong answer resets to 0.

    One statement, so there is no read-then-write gap for a crash to land in.
    """
    db.connect().execute(
        f"UPDATE {table} SET "
        f"box = CASE WHEN ? THEN MIN(box + 1, 5) ELSE 0 END, "
        f"review_count = review_count + 1, "
        f"last_reviewed_at = ?, updated_at = ?, origin = ? WHERE id = ?",
        (1 if correct else 0, db.now_ms(), db.now_ms(), db.device_id(), row_id),
    )


# --------------------------------------------------------------------------
# sticky window state (local only)
# --------------------------------------------------------------------------

def sticky_list(open_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM sticky_windows"
    if open_only:
        sql += " WHERE open = 1"
    return [dict(r) for r in db.connect().execute(sql)]


def sticky_save(state: dict[str, Any]) -> str:
    cols = ("kind", "query", "x", "y", "w", "h", "hide_answer", "on_top",
            "opacity", "color", "open")
    data = {k: state[k] for k in cols if k in state}
    sid = state.get("id") or db.new_id()
    conn = db.connect()
    if conn.execute("SELECT 1 FROM sticky_windows WHERE id = ?", (sid,)).fetchone():
        if data:
            assigns = ", ".join(f"{c} = ?" for c in data)
            conn.execute(f"UPDATE sticky_windows SET {assigns} WHERE id = ?",
                         (*data.values(), sid))
    else:
        names = ["id", *data.keys()]
        conn.execute(
            f"INSERT INTO sticky_windows ({', '.join(names)}) "
            f"VALUES ({', '.join('?' * len(names))})",
            (sid, *data.values()),
        )
    return sid


def sticky_delete(sticky_id: str) -> None:
    db.connect().execute("DELETE FROM sticky_windows WHERE id = ?", (sticky_id,))


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------

def stats() -> dict[str, int]:
    conn = db.connect()
    out: dict[str, int] = {}
    for table in ("expressions", "sentences", "grammar", "passages"):
        out[table] = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE deleted = 0"
        ).fetchone()["n"]
    out["today"] = conn.execute(
        "SELECT COUNT(*) AS n FROM expressions WHERE deleted = 0 AND studied_on = ?",
        (today(),),
    ).fetchone()["n"]
    out["weak"] = conn.execute(
        "SELECT COUNT(*) AS n FROM expressions WHERE deleted = 0 AND box <= 1"
    ).fetchone()["n"]
    return out
