from datetime import date

import pytest

import store


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test.db")
    store.init_db(path)
    return path


def test_open_card_has_no_options(db):
    store.add_cards("doc.pdf", [{"question": "Q1", "answer": "A1"}], db)
    card = store.next_due_card("doc.pdf", kind="open", db_path=db)
    assert card["options"] is None
    assert card["question"] == "Q1"


def test_quiz_card_stores_and_parses_options(db):
    store.add_cards(
        "doc.pdf",
        [{"question": "Q1", "answer": "A1", "options": ["A1", "B", "C", "D"]}],
        db,
    )
    card = store.next_due_card("doc.pdf", kind="quiz", db_path=db)
    assert card["options"] == ["A1", "B", "C", "D"]


def test_kind_filter_separates_decks(db):
    store.add_cards("doc.pdf", [{"question": "Open", "answer": "A"}], db)
    store.add_cards("doc.pdf", [{"question": "Quiz", "answer": "A", "options": ["A", "B"]}], db)
    assert store.next_due_card("doc.pdf", kind="open", db_path=db)["question"] == "Open"
    assert store.next_due_card("doc.pdf", kind="quiz", db_path=db)["question"] == "Quiz"


def test_progress_counts_per_kind(db):
    store.add_cards("doc.pdf", [{"question": "O", "answer": "A"}], db)
    store.add_cards(
        "doc.pdf",
        [
            {"question": "Q1", "answer": "A", "options": ["A", "B"]},
            {"question": "Q2", "answer": "A", "options": ["A", "B"]},
        ],
        db,
    )
    assert store.progress("doc.pdf", kind="open", db_path=db)["total"] == 1
    assert store.progress("doc.pdf", kind="quiz", db_path=db)["total"] == 2
    assert store.progress("doc.pdf", db_path=db)["total"] == 3


def test_record_review_reschedules_and_clears_due(db):
    store.add_cards("doc.pdf", [{"question": "Q", "answer": "A"}], db)
    card = store.next_due_card("doc.pdf", kind="open", db_path=db)
    schedule = store.record_review(card["id"], 5, today=date(2026, 1, 1), db_path=db)
    assert schedule["interval"] == 1
    assert schedule["due_date"] == "2026-01-02"
    assert store.next_due_card("doc.pdf", kind="open", today="2026-01-01", db_path=db) is None


def test_dashboard_maturity_buckets_new_cards(db):
    store.add_cards("doc.pdf", [{"question": "Q1", "answer": "A"}, {"question": "Q2", "answer": "A"}], db)
    data = store.dashboard(db_path=db)
    assert data["maturity"]["new"] == 2
    assert data["maturity"]["mature"] == 0


def test_dashboard_groups_by_document(db):
    store.add_cards("a.pdf", [{"question": "Q", "answer": "A"}], db)
    store.add_cards("b.pdf", [{"question": "Q", "answer": "A"}, {"question": "Q2", "answer": "A"}], db)
    by_doc = {row["document"]: row["total"] for row in store.dashboard(db_path=db)["by_document"]}
    assert by_doc == {"a.pdf": 1, "b.pdf": 2}


def test_record_review_logs_history(db):
    store.add_cards("doc.pdf", [{"question": "Q", "answer": "A"}], db)
    card = store.next_due_card("doc.pdf", kind="open", db_path=db)
    store.record_review(card["id"], 4, today=date(2026, 1, 1), db_path=db)
    today_entry = store.dashboard(today=date(2026, 1, 1), db_path=db)["reviews_history"][-1]
    assert today_entry["date"] == "2026-01-01"
    assert today_entry["count"] == 1
    assert today_entry["avg_quality"] == 4.0
