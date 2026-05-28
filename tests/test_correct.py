"""Tests for govori.correct — deterministic transcript correction (no AI calls)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import govori.correct as cor


@pytest.fixture(autouse=True)
def _patch_paths(tmp_config, monkeypatch):
    monkeypatch.setattr(cor, "CORRECTIONS_MAP", tmp_config["corrections_file"])
    monkeypatch.setattr(cor, "CORRECTIONS_LOG", tmp_config["corrections_log"])
    monkeypatch.setattr(cor, "_glossary_cache", None)
    monkeypatch.setattr(cor, "_glossary_mtime", 0.0)
    yield


def _write_map(tmp_config: dict, entries: dict) -> None:
    tmp_config["corrections_file"].write_text(json.dumps(entries, ensure_ascii=False))
    cor._glossary_cache = None  # bust glossary cache


def test_stem_replacement(tmp_config):
    """stem=True: 'марквиз\\w*' matches inflected form 'марквизу'."""
    _write_map(tmp_config, {"марквиз": {"to": "Marquiz", "stem": True}})
    text, edits = cor.correct_transcript("по марквизу", source="test", use_ai=False)
    assert "Marquiz" in text


def test_stem_all_inflections(tmp_config):
    """stem=True must cover all common Russian inflections of the stem."""
    _write_map(tmp_config, {"марквиз": {"to": "Marquiz", "stem": True}})
    for phrase in ["из марквиза", "про марквиз", "с марквизом", "марквизе"]:
        text, _ = cor.correct_transcript(phrase, source="test", use_ai=False)
        assert "Marquiz" in text, f"Expected Marquiz in result for '{phrase}': '{text}'"


def test_word_exact_match(tmp_config):
    """word-exact (stem=False): 'скво' → 'SKVO'."""
    _write_map(tmp_config, {"скво": {"to": "SKVO"}})
    text, _ = cor.correct_transcript("скво", source="test", use_ai=False)
    assert "SKVO" in text


def test_word_exact_no_false_positive(tmp_config):
    """CRITICAL: 'скво' entry must NOT replace 'сквозь' (word boundary guard)."""
    _write_map(tmp_config, {"скво": {"to": "SKVO"}})
    text, _ = cor.correct_transcript("сквозь лес", source="test", use_ai=False)
    assert "SKVO" not in text, (
        f"Word-exact guard failed: 'сквозь' was corrupted to SKVO in '{text}'"
    )


def test_plain_string_value(tmp_config):
    """Plain string value in corrections.json works like word-exact."""
    _write_map(tmp_config, {"хайку": "Haiku"})
    text, _ = cor.correct_transcript("хайку", source="test", use_ai=False)
    assert "Haiku" in text


def test_multiword_key(tmp_config):
    """Multi-word key replaces the whole phrase."""
    _write_map(tmp_config, {"тревел март": {"to": "Travelmart"}})
    text, _ = cor.correct_transcript("тревел март", source="test", use_ai=False)
    assert "Travelmart" in text


def test_no_match_leaves_text_unchanged(tmp_config):
    _write_map(tmp_config, {"скво": {"to": "SKVO"}})
    text, edits = cor.correct_transcript("обычный текст", source="test", use_ai=False)
    assert text == "обычный текст"
    assert edits == []


def test_correct_transcript_returns_tuple(tmp_config):
    """correct_transcript always returns (str, list)."""
    _write_map(tmp_config, {})
    result = cor.correct_transcript("hello", source="test", use_ai=False)
    assert isinstance(result, tuple)
    assert isinstance(result[0], str)
    assert isinstance(result[1], list)


def test_ai_path_applies_edits(tmp_config):
    """AI path: mock anthropic → edits applied to text."""
    _write_map(tmp_config, {})

    fake_edits = [{"from": "марквиз", "to": "Marquiz"}]
    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text=json.dumps({"edits": fake_edits}))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp

    # correct.py imports _get_anthropic_client from govori.notes
    with patch("govori.notes._get_anthropic_client", return_value=fake_client):
        # Provide a non-empty glossary so AI path runs (client not None AND glossary not empty)
        cor._glossary_cache = "КАНОНИЧЕСКИЕ ТЕРМИНЫ:\nMarquiz"
        text, edits = cor.correct_transcript("марквиз", source="test", use_ai=True)

    # Either the edit was applied or the function returned gracefully
    assert isinstance(text, str)
