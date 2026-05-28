"""Unit tests for govori.review — pending_edits, dictionary_entries, accept/remove/mark_reviewed."""
from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

import pytest


for _mod in ["AppKit", "Foundation", "Cocoa", "objc"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


import govori.review as rev


@pytest.fixture(autouse=True)
def _patch_review_paths(tmp_config, monkeypatch):
    monkeypatch.setattr(rev, "CORRECTIONS_LOG", tmp_config["corrections_log"])
    monkeypatch.setattr(rev, "CORRECTIONS_MAP", tmp_config["corrections_file"])
    yield


# ---------------------------------------------------------------------------
# pending_edits
# ---------------------------------------------------------------------------

def test_pending_edits_empty(tmp_config):
    tmp_config["corrections_log"].write_text("")
    result = rev.pending_edits()
    assert result == []


def test_pending_edits_with_data(tmp_config):
    record = {
        "ts": "2024-01-01T00:00:00",
        "edits": [{"from": "марквиз", "to": "Marquiz"}],
        "corrected": "Marquiz это квиз",
        "source": "test",
        "reviewed": False,
    }
    tmp_config["corrections_log"].write_text(json.dumps(record, ensure_ascii=False) + "\n")
    result = rev.pending_edits()
    assert len(result) == 1
    assert result[0]["from"] == "марквиз"
    assert result[0]["to"] == "Marquiz"


def test_pending_edits_skips_reviewed(tmp_config):
    records = [
        {"ts": "t1", "edits": [{"from": "a", "to": "B"}], "reviewed": True},
        {"ts": "t2", "edits": [{"from": "c", "to": "D"}], "reviewed": False},
    ]
    tmp_config["corrections_log"].write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"
    )
    result = rev.pending_edits()
    assert len(result) == 1
    assert result[0]["from"] == "c"


# ---------------------------------------------------------------------------
# dictionary_entries
# ---------------------------------------------------------------------------

def test_dictionary_entries_empty(tmp_config):
    tmp_config["corrections_file"].write_text("{}")
    result = rev.dictionary_entries()
    assert result == []


def test_dictionary_entries_with_data(tmp_config):
    data = {"слово": "Word", "марквиз": {"to": "Marquiz", "stem": True}}
    tmp_config["corrections_file"].write_text(json.dumps(data, ensure_ascii=False))
    result = rev.dictionary_entries()
    assert len(result) == 2
    frm_values = {e["from"] for e in result}
    assert "слово" in frm_values
    assert "марквиз" in frm_values


def test_dictionary_entries_stem_flag(tmp_config):
    data = {"марквиз": {"to": "Marquiz", "stem": True}}
    tmp_config["corrections_file"].write_text(json.dumps(data, ensure_ascii=False))
    result = rev.dictionary_entries()
    assert result[0]["stem"] is True


# ---------------------------------------------------------------------------
# accept_correction
# ---------------------------------------------------------------------------

def test_accept_correction_writes_to_file(tmp_config):
    rev.accept_correction("тест", "Test")
    data = json.loads(tmp_config["corrections_file"].read_text())
    assert "тест" in data
    assert data["тест"] == "Test"


def test_accept_correction_overwrites_existing(tmp_config):
    tmp_config["corrections_file"].write_text(json.dumps({"тест": "OldValue"}))
    rev.accept_correction("тест", "NewValue")
    data = json.loads(tmp_config["corrections_file"].read_text())
    assert data["тест"] == "NewValue"


def test_accept_correction_empty_args_no_crash(tmp_config):
    """accept_correction with empty strings → no crash, no write."""
    rev.accept_correction("", "Test")
    rev.accept_correction("Test", "")
    # File stays as-is (empty {})
    data = json.loads(tmp_config["corrections_file"].read_text())
    assert data == {}


# ---------------------------------------------------------------------------
# remove_correction
# ---------------------------------------------------------------------------

def test_remove_correction(tmp_config):
    tmp_config["corrections_file"].write_text(json.dumps({"убери": "Remove", "оставь": "Keep"}))
    rev.remove_correction("убери")
    data = json.loads(tmp_config["corrections_file"].read_text())
    assert "убери" not in data
    assert "оставь" in data


def test_remove_correction_missing_key_no_crash(tmp_config):
    rev.remove_correction("несуществующее")  # should not raise


# ---------------------------------------------------------------------------
# mark_reviewed
# ---------------------------------------------------------------------------

def test_mark_reviewed(tmp_config):
    record = {
        "ts": "2024-01-01T12:00:00",
        "edits": [{"from": "a", "to": "B"}],
        "reviewed": False,
    }
    tmp_config["corrections_log"].write_text(json.dumps(record, ensure_ascii=False) + "\n")
    rev.mark_reviewed("2024-01-01T12:00:00")
    # After marking, pending_edits should be empty
    result = rev.pending_edits()
    assert result == []


def test_mark_reviewed_nonexistent_ts_no_crash(tmp_config):
    tmp_config["corrections_log"].write_text("")
    rev.mark_reviewed("totally_fake_timestamp")
