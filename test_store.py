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


def test_ensure_skills_is_idempotent(db):
    store.ensure_skills(["modexp", "rsa_verify"], db_path=db)
    store.ensure_skills(["modexp", "rsa_verify"], db_path=db)
    assert store.skills_progress(db_path=db)["total"] == 2


def test_next_due_skill_returns_seeded_then_none_after_review(db):
    store.ensure_skills(["modexp"], today="2026-01-01", db_path=db)
    assert store.next_due_skill(today="2026-01-01", db_path=db) == "modexp"
    store.record_skill_review("modexp", 5, today=date(2026, 1, 1), db_path=db)
    assert store.next_due_skill(today="2026-01-01", db_path=db) is None


def test_record_skill_review_reschedules(db):
    store.ensure_skills(["modexp"], today="2026-01-01", db_path=db)
    schedule = store.record_skill_review("modexp", 5, today=date(2026, 1, 1), db_path=db)
    assert schedule["interval"] == 1
    assert schedule["due_date"] == "2026-01-02"


def test_all_cards_orders_by_document_then_id(db):
    store.add_cards("b.pdf", [{"question": "Q1", "answer": "A1"}], db)
    store.add_cards("a.pdf", [{"question": "Q2", "answer": "A2", "options": ["A2", "X"]}], db)
    cards = store.all_cards(db_path=db)
    assert [c["document"] for c in cards] == ["a.pdf", "b.pdf"]
    assert cards[0]["options"] == ["A2", "X"]
    assert cards[1]["options"] is None


def test_all_cards_filters_by_document(db):
    store.add_cards("a.pdf", [{"question": "Q1", "answer": "A1"}], db)
    store.add_cards("b.pdf", [{"question": "Q2", "answer": "A2"}], db)
    cards = store.all_cards("b.pdf", db_path=db)
    assert [c["question"] for c in cards] == ["Q2"]


def test_set_document_subject_upserts(db):
    store.set_document_subject("a.pdf", "crypto", db)
    store.set_document_subject("a.pdf", "maths", db)
    assert store.document_subjects(db_path=db) == {"a.pdf": "maths"}


def test_set_document_subject_blank_stores_null(db):
    store.set_document_subject("a.pdf", "  ", db)
    assert store.document_subjects(db_path=db) == {"a.pdf": None}
    assert store.subjects(db_path=db) == []


def test_subjects_lists_distinct_sorted(db):
    store.set_document_subject("a.pdf", "reseaux", db)
    store.set_document_subject("b.pdf", "crypto", db)
    store.set_document_subject("c.pdf", "crypto", db)
    assert store.subjects(db_path=db) == ["crypto", "reseaux"]


def test_documents_in_subject_returns_names(db):
    store.set_document_subject("b.pdf", "crypto", db)
    store.set_document_subject("a.pdf", "crypto", db)
    assert store.documents_in_subject("crypto", db_path=db) == ["a.pdf", "b.pdf"]


def test_all_cards_filters_by_subject(db):
    store.set_document_subject("rsa.pdf", "crypto", db)
    store.set_document_subject("tcp.pdf", "reseaux", db)
    store.add_cards("rsa.pdf", [{"question": "Q1", "answer": "A1"}], db)
    store.add_cards("tcp.pdf", [{"question": "Q2", "answer": "A2"}], db)
    cards = store.all_cards(subject="crypto", db_path=db)
    assert [c["question"] for c in cards] == ["Q1"]


def test_progress_filters_by_subject(db):
    store.set_document_subject("rsa.pdf", "crypto", db)
    store.add_cards("rsa.pdf", [{"question": "Q", "answer": "A"}], db)
    store.add_cards("tcp.pdf", [{"question": "Q2", "answer": "A2"}], db)
    assert store.progress(subject="crypto", db_path=db)["total"] == 1


def test_subject_scope_includes_cards_tagged_with_subject_name(db):
    store.add_cards("crypto", [{"question": "Qsub", "answer": "A"}], db)
    assert [c["question"] for c in store.all_cards(subject="crypto", db_path=db)] == ["Qsub"]


def test_delete_document_removes_cards_and_subject(db):
    store.set_document_subject("gone.pdf", "crypto", db)
    store.add_cards("gone.pdf", [{"question": "Q", "answer": "A"}], db)
    store.add_cards("keep.pdf", [{"question": "Q2", "answer": "A2"}], db)
    store.delete_document("gone.pdf", db)
    assert [c["question"] for c in store.all_cards(db_path=db)] == ["Q2"]
    assert store.document_subjects(db_path=db) == {}


def test_delete_document_removes_review_history(db):
    store.add_cards("gone.pdf", [{"question": "Q", "answer": "A"}], db)
    card = store.next_due_card("gone.pdf", kind="open", db_path=db)
    store.record_review(card["id"], 4, today=date(2026, 1, 1), db_path=db)
    store.delete_document("gone.pdf", db)
    history = store.dashboard(today=date(2026, 1, 1), db_path=db)["reviews_history"][-1]
    assert history["count"] == 0


def test_record_review_logs_history(db):
    store.add_cards("doc.pdf", [{"question": "Q", "answer": "A"}], db)
    card = store.next_due_card("doc.pdf", kind="open", db_path=db)
    store.record_review(card["id"], 4, today=date(2026, 1, 1), db_path=db)
    today_entry = store.dashboard(today=date(2026, 1, 1), db_path=db)["reviews_history"][-1]
    assert today_entry["date"] == "2026-01-01"
    assert today_entry["count"] == 1
    assert today_entry["avg_quality"] == 4.0
