"""Persistance SQLite du deck de cartes de révision et de leur planning SM-2."""

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


def init_db(db_path=DB_PATH):
    with _lock, _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                ease REAL NOT NULL DEFAULT 2.5,
                repetitions INTEGER NOT NULL DEFAULT 0,
                interval INTEGER NOT NULL DEFAULT 0,
                due_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def add_cards(document, cards, db_path=DB_PATH):
    today = date.today().isoformat()
    rows = [(document, c["question"], c["answer"], today, today) for c in cards]
    with _lock, _connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO cards (document, question, answer, due_date, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def next_due_card(document=None, today=None, db_path=DB_PATH):
    today = today or date.today().isoformat()
    query = "SELECT * FROM cards WHERE due_date <= ?"
    params = [today]
    if document:
        query += " AND document = ?"
        params.append(document)
    query += " ORDER BY due_date ASC, id ASC LIMIT 1"
    with _lock, _connect(db_path) as conn:
        row = conn.execute(query, params).fetchone()
    return dict(row) if row else None


def get_card(card_id, db_path=DB_PATH):
    with _lock, _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return dict(row) if row else None


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


def progress(document=None, today=None, db_path=DB_PATH):
    today = today or date.today().isoformat()
    where = ""
    params = []
    if document:
        where = " WHERE document = ?"
        params = [document]
    with _lock, _connect(db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM cards{where}", params).fetchone()["n"]
        due_query = f"SELECT COUNT(*) AS n FROM cards{where}{' AND' if where else ' WHERE'} due_date <= ?"
        due = conn.execute(due_query, params + [today]).fetchone()["n"]
        learned_query = f"SELECT COUNT(*) AS n FROM cards{where}{' AND' if where else ' WHERE'} repetitions >= ?"
        learned = conn.execute(learned_query, params + [LEARNED_REPETITIONS]).fetchone()["n"]
    return {"total": total, "due": due, "learned": learned}
