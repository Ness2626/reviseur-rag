"""Persistance SQLite du deck de cartes de révision et de leur planning SM-2."""

import json
import sqlite3
import threading
from datetime import date, timedelta

import scheduler

DB_PATH = "revision.db"
LEARNED_REPETITIONS = 3
YOUNG_INTERVAL_DAYS = 7
MATURE_INTERVAL_DAYS = 21
DUE_HORIZON_DAYS = 34
HISTORY_DAYS = 13
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER NOT NULL,
                quality INTEGER NOT NULL,
                reviewed_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS skills (
                kind TEXT PRIMARY KEY,
                ease REAL NOT NULL DEFAULT 2.5,
                repetitions INTEGER NOT NULL DEFAULT 0,
                interval INTEGER NOT NULL DEFAULT 0,
                due_date TEXT NOT NULL
            )
            """
        )


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
        conn.execute(
            "INSERT INTO reviews (card_id, quality, reviewed_at) VALUES (?, ?, ?)",
            (card_id, quality, review_day.isoformat()),
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


def ensure_skills(kinds, today=None, db_path=DB_PATH):
    today = today or date.today().isoformat()
    with _lock, _connect(db_path) as conn:
        for kind in kinds:
            conn.execute(
                "INSERT OR IGNORE INTO skills (kind, due_date) VALUES (?, ?)",
                (kind, today),
            )


def next_due_skill(today=None, db_path=DB_PATH):
    today = today or date.today().isoformat()
    with _lock, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT kind FROM skills WHERE due_date <= ? ORDER BY due_date ASC, kind ASC LIMIT 1",
            (today,),
        ).fetchone()
    return row["kind"] if row else None


def record_skill_review(kind, quality, today=None, db_path=DB_PATH):
    review_day = today or date.today()
    with _lock, _connect(db_path) as conn:
        row = conn.execute(
            "SELECT ease, repetitions, interval FROM skills WHERE kind = ?", (kind,)
        ).fetchone()
        if row is None:
            return None
        state = scheduler.CardState(row["ease"], row["repetitions"], row["interval"])
        updated = scheduler.review(state, quality)
        due = scheduler.next_due_date(updated.interval, review_day)
        conn.execute(
            "UPDATE skills SET ease = ?, repetitions = ?, interval = ?, due_date = ? WHERE kind = ?",
            (updated.ease, updated.repetitions, updated.interval, due.isoformat(), kind),
        )
    return {"interval": updated.interval, "due_date": due.isoformat()}


def skills_progress(today=None, db_path=DB_PATH):
    today = today or date.today().isoformat()
    with _lock, _connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM skills").fetchone()["n"]
        due = conn.execute(
            "SELECT COUNT(*) AS n FROM skills WHERE due_date <= ?", (today,)
        ).fetchone()["n"]
        learned = conn.execute(
            "SELECT COUNT(*) AS n FROM skills WHERE repetitions >= ?", (LEARNED_REPETITIONS,)
        ).fetchone()["n"]
    return {"total": total, "due": due, "learned": learned}


def _maturity_bucket(repetitions, interval):
    if repetitions == 0:
        return "new"
    if interval < YOUNG_INTERVAL_DAYS:
        return "learning"
    if interval < MATURE_INTERVAL_DAYS:
        return "young"
    return "mature"


def dashboard(document=None, today=None, db_path=DB_PATH):
    today = today or date.today()
    today_iso = today.isoformat()
    card_filter = " WHERE document = ?" if document else ""
    card_params = [document] if document else []

    review_join = " WHERE c.document = ?" if document else ""
    review_params = [document] if document else []

    with _lock, _connect(db_path) as conn:
        maturity = {"new": 0, "learning": 0, "young": 0, "mature": 0}
        for row in conn.execute(f"SELECT repetitions, interval FROM cards{card_filter}", card_params):
            maturity[_maturity_bucket(row["repetitions"], row["interval"])] += 1

        success_by_doc = {
            row["document"]: (row["n"], row["ok"])
            for row in conn.execute(
                "SELECT c.document AS document, COUNT(*) AS n, "
                "SUM(CASE WHEN r.quality >= 3 THEN 1 ELSE 0 END) AS ok "
                "FROM reviews r JOIN cards c ON c.id = r.card_id"
                f"{review_join} GROUP BY c.document",
                review_params,
            )
        }

        by_document = []
        for row in conn.execute(
            f"SELECT document, COUNT(*) AS total, "
            f"SUM(CASE WHEN repetitions >= {LEARNED_REPETITIONS} THEN 1 ELSE 0 END) AS learned, "
            f"SUM(CASE WHEN due_date <= ? THEN 1 ELSE 0 END) AS due, "
            f"SUM(CASE WHEN due_date <= ? AND options IS NOT NULL THEN 1 ELSE 0 END) AS due_quiz, "
            f"SUM(CASE WHEN due_date <= ? AND options IS NULL THEN 1 ELSE 0 END) AS due_open "
            f"FROM cards{card_filter} GROUP BY document ORDER BY total DESC",
            [today_iso, today_iso, today_iso] + card_params,
        ):
            reviewed, ok = success_by_doc.get(row["document"], (0, 0))
            by_document.append({
                "document": row["document"], "total": row["total"], "learned": row["learned"],
                "due": row["due"], "due_quiz": row["due_quiz"], "due_open": row["due_open"],
                "reviewed": reviewed,
                "success_rate": round(ok / reviewed * 100) if reviewed else None,
            })

        due_map = {
            row["due_date"]: row["n"]
            for row in conn.execute(
                f"SELECT due_date, COUNT(*) AS n FROM cards{card_filter} GROUP BY due_date",
                card_params,
            )
        }

        review_map = {
            row["day"]: (row["n"], row["avgq"])
            for row in conn.execute(
                "SELECT r.reviewed_at AS day, COUNT(*) AS n, AVG(r.quality) AS avgq "
                "FROM reviews r JOIN cards c ON c.id = r.card_id"
                f"{review_join} GROUP BY r.reviewed_at",
                review_params,
            )
        }

    overdue = sum(n for day, n in due_map.items() if day < today_iso)
    due_calendar = [
        {"date": (today + timedelta(days=offset)).isoformat(),
         "count": due_map.get((today + timedelta(days=offset)).isoformat(), 0)}
        for offset in range(DUE_HORIZON_DAYS + 1)
    ]
    reviews_history = []
    for offset in range(HISTORY_DAYS, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        count, avg_quality = review_map.get(day, (0, None))
        reviews_history.append({
            "date": day,
            "count": count,
            "avg_quality": round(avg_quality, 2) if avg_quality is not None else None,
        })

    return {
        "maturity": maturity,
        "by_document": by_document,
        "overdue": overdue,
        "due_calendar": due_calendar,
        "reviews_history": reviews_history,
    }
