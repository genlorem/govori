"""Trailing 'продолжение следует' — STT artefact glued to the end of real speech."""
from __future__ import annotations

import importlib
import io
import sys
from unittest.mock import MagicMock

import pytest

for _mod in ["AppKit", "Foundation", "Cocoa", "objc"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


@pytest.fixture(scope="module")
def tr():
    """Real govori.transcribe — test_server.py replaces it with a MagicMock globally."""
    saved = sys.modules.pop("govori.transcribe", None)
    mod = importlib.import_module("govori.transcribe")
    yield mod
    if saved is not None:
        sys.modules["govori.transcribe"] = saved


@pytest.mark.parametrize("raw,expected", [
    ("Купи молоко. Продолжение следует...", "Купи молоко."),
    ("Купи молоко, продолжение следует", "Купи молоко"),
    ("Купи молоко Продолжение следует.", "Купи молоко"),
    ("Купи молоко. ПРОДОЛЖЕНИЕ СЛЕДУЕТ…", "Купи молоко."),
    ("Купи молоко. Продолжение следует. Продолжение следует...", "Купи молоко."),
    ("Продолжение следует...", ""),
])
def test_trailing_tail_is_cut(tr, raw, expected):
    assert tr.strip_trailing_hallucination(raw) == expected


@pytest.mark.parametrize("raw", [
    "Купи молоко",
    "Продолжение следует после паузы",
    "",
    None,
])
def test_untouched_when_no_tail(tr, raw):
    assert tr.strip_trailing_hallucination(raw) == raw


def test_phrase_only_text_still_filtered_as_hallucination(tr):
    assert tr._is_hallucination(tr.strip_trailing_hallucination("Продолжение следует..."))


def test_api_result_is_trimmed(tr):
    client = MagicMock()
    client.with_options.return_value.audio.transcriptions.create.return_value = MagicMock(
        text="  Напомни про встречу. Продолжение следует...  "
    )
    got = tr._call_transcription_api(client, "whisper-large-v3-turbo", io.BytesIO())
    assert got == "Напомни про встречу."
