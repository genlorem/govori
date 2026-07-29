"""Unit tests for govori.intents — do-action router, session_ask executor, decision log."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from govori import intents


SESSIONS = [{"id": "session-manager__spark"}, {"id": "govori__main"}]


def _fake_anthropic_response(payload: dict):
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(payload, ensure_ascii=False))]
    return resp


class TestClassifyDoAction:
    def test_no_live_sessions_short_circuits(self, monkeypatch):
        monkeypatch.setattr(intents.session_control, "list_sessions", lambda: [])
        result = intents.classify_do_action("спроси у session-manager когда будет готово")
        assert result == {"action": "other", "message": None, "candidates": []}

    def test_notes_cfg_missing_returns_default(self, monkeypatch):
        monkeypatch.setattr(intents.session_control, "list_sessions", lambda: SESSIONS)
        monkeypatch.setattr(intents.cfg, "NOTES_CFG", None)
        result = intents.classify_do_action("спроси у session-manager когда будет готово")
        assert result["action"] == "other"

    def test_anthropic_unavailable_returns_default(self, monkeypatch):
        monkeypatch.setattr(intents.session_control, "list_sessions", lambda: SESSIONS)
        monkeypatch.setattr(intents.cfg, "NOTES_CFG", {"classifier_model": "test-model"})
        monkeypatch.setattr(intents.notes, "_get_anthropic_client", lambda: None)
        result = intents.classify_do_action("спроси у session-manager когда будет готово")
        assert result["action"] == "other"

    def test_session_ask_recognized_and_filtered_to_live_candidates(self, monkeypatch):
        monkeypatch.setattr(intents.session_control, "list_sessions", lambda: SESSIONS)
        monkeypatch.setattr(intents.cfg, "NOTES_CFG", {"classifier_model": "test-model"})
        fake_client = MagicMock()
        fake_client.messages.create.return_value = _fake_anthropic_response({
            "action": "session_ask",
            "message": "когда будет готово",
            "candidates": ["session-manager__spark", "unknown-session", "govori__main"],
        })
        monkeypatch.setattr(intents.notes, "_get_anthropic_client", lambda: fake_client)
        result = intents.classify_do_action("спроси у session-manager когда будет готово")
        assert result["action"] == "session_ask"
        assert result["message"] == "когда будет готово"
        # "unknown-session" is not a live session id -> filtered out
        assert result["candidates"] == ["session-manager__spark", "govori__main"]

    def test_action_other_from_model_returns_default(self, monkeypatch):
        monkeypatch.setattr(intents.session_control, "list_sessions", lambda: SESSIONS)
        monkeypatch.setattr(intents.cfg, "NOTES_CFG", {"classifier_model": "test-model"})
        fake_client = MagicMock()
        fake_client.messages.create.return_value = _fake_anthropic_response({
            "action": "other", "message": None, "candidates": [],
        })
        monkeypatch.setattr(intents.notes, "_get_anthropic_client", lambda: fake_client)
        result = intents.classify_do_action("напомни купить молоко")
        assert result == {"action": "other", "message": None, "candidates": []}

    def test_malformed_model_response_returns_default(self, monkeypatch):
        monkeypatch.setattr(intents.session_control, "list_sessions", lambda: SESSIONS)
        monkeypatch.setattr(intents.cfg, "NOTES_CFG", {"classifier_model": "test-model"})
        fake_client = MagicMock()
        bad_resp = MagicMock()
        bad_resp.content = [MagicMock(text="not json at all")]
        fake_client.messages.create.return_value = bad_resp
        monkeypatch.setattr(intents.notes, "_get_anthropic_client", lambda: fake_client)
        result = intents.classify_do_action("бла бла бла")
        assert result == {"action": "other", "message": None, "candidates": []}


class TestSessionAskExecute:
    def test_success_returns_confirmation(self, monkeypatch):
        monkeypatch.setattr(
            intents.session_control, "ask_session",
            lambda target, question: {"ok": True},
        )
        answer = intents.session_ask_execute("session-manager__spark", "когда будет готово")
        assert answer == "✓ отправлено в session-manager__spark"

    def test_tags_message_with_voice_prefix(self, monkeypatch):
        captured = {}

        def fake_ask(target, question):
            captured["target"] = target
            captured["question"] = question
            return {"ok": True}

        monkeypatch.setattr(intents.session_control, "ask_session", fake_ask)
        intents.session_ask_execute("session-manager__spark", "когда будет готово")
        assert captured["target"] == "session-manager__spark"
        assert captured["question"].startswith("[голос/Говори")
        assert captured["question"].endswith("когда будет готово")

    def test_failure_returns_error_string(self, monkeypatch):
        monkeypatch.setattr(
            intents.session_control, "ask_session",
            lambda target, question: {"ok": False, "error": "connection refused"},
        )
        answer = intents.session_ask_execute("session-manager__spark", "когда будет готово")
        assert "не смог" in answer.lower()
        assert "connection refused" in answer


class TestLogIntentDecision:
    def test_appends_jsonl_line(self, tmp_path, monkeypatch):
        log_path = tmp_path / "intent-decisions.jsonl"
        monkeypatch.setattr(intents, "_DECISION_LOG", log_path)
        intents.log_intent_decision({"predicted_intent": "note", "chosen_intent": "note"})
        intents.log_intent_decision({"predicted_intent": "ask", "chosen_intent": "ask"})
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["predicted_intent"] == "note"
        assert "ts" in first

    def test_creates_parent_dir(self, tmp_path, monkeypatch):
        log_path = tmp_path / "nested" / "dir" / "intent-decisions.jsonl"
        monkeypatch.setattr(intents, "_DECISION_LOG", log_path)
        intents.log_intent_decision({"chosen_intent": "do"})
        assert log_path.exists()

    def test_never_raises_on_failure(self, monkeypatch):
        fake_log = MagicMock()
        fake_log.open.side_effect = OSError("disk full")
        monkeypatch.setattr(intents, "_DECISION_LOG", fake_log)
        intents.log_intent_decision({"chosen_intent": "do"})  # must not raise
