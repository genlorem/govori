"""Configuration loading and plugin discovery for Govori."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


HOME = Path.home()
CONFIG_DIR = HOME / ".config" / "govori"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
PLUGINS_DIR = CONFIG_DIR / "plugins"
SETUP_DONE_FILE = CONFIG_DIR / ".setup_done"
LOG_FILE = CONFIG_DIR / "govori.log"


class GovoriConfig(BaseModel):
    language: str = Field(default="ru", pattern=r"^(en|ru)$")
    model: str = Field(default="whisper-large-v3-turbo")
    note_model: Optional[str] = Field(default="whisper-large-v3")
    note_relay_url: Optional[str] = Field(default=None)
    note_relay_token: Optional[str] = Field(default=None)
    sample_rate: int = Field(default=16000, ge=8000, le=48000)
    whisper_prompt: str = Field(default="")
    base_url: Optional[str] = Field(default=None)
    api_key_env: str = Field(default="GROQ_API_KEY")
    predict_model: str = Field(default="llama-3.3-70b-versatile")

    @field_validator("base_url")
    @classmethod
    def base_url_must_be_http(cls, value):
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value


CONFIG = GovoriConfig()
PLUGINS: dict = {}
SAMPLE_RATE = CONFIG.sample_rate
LANGUAGE = CONFIG.language
MODEL = CONFIG.model
WHISPER_PROMPT = ""
NOTES_CFG = None


def _cfg_get(config, key, default=None):
    if isinstance(config, GovoriConfig):
        return getattr(config, key, default)
    return config.get(key, default)


def _load_yaml(path: Path):
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise SystemExit(
            f"\n✗ Invalid YAML in {path}:\n  {e}\n\n"
            "  Check syntax (indentation, quotes, colons). Run `govori setup` to regenerate.\n"
        ) from e


def _load_yaml_list(path: Path):
    """Load a YAML file expected to contain a list."""
    data = _load_yaml(path)
    if isinstance(data, list):
        return data
    return []


def load_config(path: Path = CONFIG_FILE) -> GovoriConfig:
    if not path.exists():
        return GovoriConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise SystemExit(
            f"\n✗ Invalid YAML in {path}:\n  {e}\n\n"
            "  Check syntax (indentation, quotes, colons). Run `govori setup` to regenerate.\n"
        ) from e
    if raw is None:
        return GovoriConfig()
    if not isinstance(raw, dict):
        raise SystemExit(
            f"\n✗ Config in {path} must be a YAML mapping, got {type(raw).__name__}.\n"
        )
    try:
        return GovoriConfig(**raw)
    except ValidationError as e:
        lines = ["", f"✗ Invalid config in {path}:"]
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            lines.append(f"  {loc}: {err['msg']}")
        lines.append("")
        raise SystemExit("\n".join(lines)) from e


def load_plugins():
    """Discover and load all plugins from ~/.config/govori/plugins/."""
    plugins = {}
    if not PLUGINS_DIR.exists():
        return plugins
    for d in sorted(PLUGINS_DIR.iterdir()):
        if not d.is_dir():
            continue
        plugin_yaml = d / "plugin.yaml"
        if not plugin_yaml.exists():
            continue
        meta = _load_yaml(plugin_yaml)
        meta["_dir"] = d
        meta["_name"] = d.name

        contexts_file = d / "contexts.yaml"
        if contexts_file.exists():
            meta["contexts"] = _load_yaml_list(contexts_file)

        stuck_file = d / "stuck.yaml"
        if stuck_file.exists():
            meta["stuck"] = _load_yaml_list(stuck_file)

        plugins[d.name] = meta
    return plugins


_PROMPT_BUDGET_BYTES = 896
_PROMPT_BUDGET_CHARS = _PROMPT_BUDGET_BYTES


def _tokenize_prompt_terms(text):
    """Split a prompt string into individual vocabulary terms."""
    terms = []
    for part in re.split(r"[,.;\n]", text):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            part = part.rsplit(":", 1)[1].strip()
        if part and len(part) <= 40:
            terms.append(part)
    return terms


def _notes_corpus_text(plugins):
    """Lowercased concatenation of all .md notes under plugin output_dirs."""
    bases = set()
    for plugin in plugins.values():
        out = plugin.get("output_dir")
        if not out:
            continue
        base_str = out.split("{", 1)[0].rstrip("/") or out
        bases.add(Path(base_str).expanduser())

    chunks = []
    for base in bases:
        if not base.exists():
            continue
        for md in base.rglob("*.md"):
            try:
                chunks.append(md.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
    return "\n".join(chunks).lower()


def build_whisper_prompt(config, plugins, budget_bytes=_PROMPT_BUDGET_BYTES):
    """Assemble a byte-budget-constrained Whisper prompt from config + plugins."""
    raw_parts = []
    base_cfg = (_cfg_get(config, "whisper_prompt", "") or "").strip()
    if base_cfg:
        raw_parts.append(base_cfg)
    for plugin in plugins.values():
        p = plugin.get("whisper_prompt", "").strip()
        if p:
            raw_parts.append(p)

    seen = set()
    terms = []
    for part in raw_parts:
        for t in _tokenize_prompt_terms(part):
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            terms.append(t)
    if not terms:
        return ""

    corpus = _notes_corpus_text(plugins)
    scored = sorted(
        (-max(1, corpus.count(t.lower())), idx, t) for idx, t in enumerate(terms)
    )

    kept, dropped = [], []
    remaining = budget_bytes
    for _, _, term in scored:
        cost = len(term.encode("utf-8")) + (2 if kept else 0)
        if cost <= remaining:
            kept.append(term)
            remaining -= cost
        else:
            dropped.append(term)

    return ", ".join(kept)


def build_notes_config(plugins):
    """Extract notes plugin config (contexts, stuck, paths, classifier)."""
    notes = plugins.get("notes")
    if not notes:
        return None

    contexts = notes.get("contexts", [])
    stuck = notes.get("stuck", [])

    valid_contexts = {c["key"] for c in contexts}
    valid_stuck = {s["key"] for s in stuck}

    contexts_desc = "\n".join(
        f"- {c['key']}: {c['description']}" for c in contexts
    )
    stuck_desc = "\n".join(
        f"- {s['key']}: {s['description']}" for s in stuck
    )

    output_dir = notes.get("output_dir", "~/govori-notes/{year}/{month}")
    index_file = notes.get("index_file", "~/govori-notes/index/recent.jsonl")

    return {
        "classifier_model": notes.get("classifier_model", "claude-haiku-4-5-20251001"),
        "output_dir": output_dir,
        "index_file": index_file,
        "valid_contexts": valid_contexts,
        "valid_stuck": valid_stuck,
        "contexts_desc": contexts_desc,
        "stuck_desc": stuck_desc,
    }


def install_runtime_config(config: GovoriConfig, plugins: dict, *, model: str | None = None) -> None:
    global CONFIG, PLUGINS, SAMPLE_RATE, LANGUAGE, MODEL, WHISPER_PROMPT, NOTES_CFG
    CONFIG = config
    PLUGINS = plugins
    SAMPLE_RATE = config.sample_rate
    LANGUAGE = config.language
    MODEL = model or config.model
    WHISPER_PROMPT = build_whisper_prompt(config, plugins)
    NOTES_CFG = build_notes_config(plugins)
