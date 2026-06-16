"""Persistance SQLite du deck de cartes de révision et de leur planning SM-2."""

import json
import sqlite3
import threading
from datetime import date

import scheduler

DB_PATH = "revision.db"
LEARNED_REPETITIONS = 3
_lock = threading.Lock()


def _connect(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _kind_clause(kind):
    if kind == "open":
        return "options IS NULL"
    if kind == "quiz":
        return "options IS NOT NULL"
    return None


def _row_to_card(row):
    if row is None:
        return None
    card = dict(row)
    card["options"] = json.loads(card["options"]) if card.get("options") else None
    return card


def init_db(db_path=DB_PATH):
    with _lock, _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                options TEXT,
                explanation TEXT,
                ease REAL NOT NULL DEFAULT 2.5,
                repetitions INTEGER NOT NULL DEFAULT 0,
                interval INTEGER NOT NULL DEFAULT 0,
                due_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(cards)")}
        if "options" not in columns:
            conn.execute("ALTER TABLE cards ADD COLUMN options TEXT")
        if "explanation" not in columns:
            conn.execute("ALTER TABLE cards ADD COLUMN explanation TEXT")


def add_cards(document, cards, db_path=DB_PATH):
    today = date.today().isoformat()
    rows = [
        (
            document,
            c["question"],
            c["answer"],
            json.dumps(c["options"]) if c.get("options") else None,
            c.get("explanation"),
            today,
            today,
        )
        for c in cards
    ]
    with _lock, _connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO cards (document, question, answer, options, explanation, due_date, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def next_due_card(document=None, kind=None, today=None, db_path=DB_PATH):
    today = today or date.today().isoformat()
    clauses = ["due_date <= ?"]
    params = [today]
    if document:
        clauses.append("document = ?")
        params.append(document)
    kind_clause = _kind_clause(kind)
    if kind_clause:
        clauses.append(kind_clause)
    query = (
        "SELECT * FROM cards WHERE " + " AND ".join(clauses)
        + " ORDER BY due_date ASC, id ASC LIMIT 1"
    )
    with _lock, _connect(db_path) as conn:
        row = conn.execute(query, params).fetchone()
    return _row_to_card(row)


def get_card(card_id, db_path=DB_PATH):
    with _lock, _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return _row_to_card(row)


def record_review(card_id, quality, today=None, db_path=DB_PATH):
    review_day = today or date.today()
    with _lock, _connect(db_path) as conn:
        row = conn.execute("SELECT ease, repetitions, interval FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return None
        state = scheduler.CardState(row["ease"], row["repetitions"], row["interval"])
        updated = scheduler.review(state, quality)
        due = scheduler.next_due_date(updated.interval, review_day)
        conn.execute(
            "UPDATE cards SET ease = ?, repetitions = ?, interval = ?, due_date = ? WHERE id = ?",
            (updated.ease, updated.repetitions, updated.interval, due.isoformat(), card_id),
        )
    return {"interval": updated.interval, "due_date": due.isoformat()}


def progress(document=None, kind=None, today=None, db_path=DB_PATH):
    today = today or date.today().isoformat()
    base = []
    params = []
    if document:
        base.append("document = ?")
        params.append(document)
    kind_clause = _kind_clause(kind)
    if kind_clause:
        base.append(kind_clause)

    def where(extra=None):
        clauses = base + ([extra] if extra else [])
        return (" WHERE " + " AND ".join(clauses)) if clauses else ""

    with _lock, _connect(db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM cards{where()}", params).fetchone()["n"]
        due = conn.execute(
            f"SELECT COUNT(*) AS n FROM cards{where('due_date <= ?')}", params + [today]
        ).fetchone()["n"]
        learned = conn.execute(
            f"SELECT COUNT(*) AS n FROM cards{where('repetitions >= ?')}",
            params + [LEARNED_REPETITIONS],
        ).fetchone()["n"]
    return {"total": total, "due": due, "learned": learned}
