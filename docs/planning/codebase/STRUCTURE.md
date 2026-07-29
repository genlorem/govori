# Codebase Structure

**Analysis Date:** 2026-04-15

## Directory Layout

```
govori/                          # Project root
├── govori.py                    # Entire application — daemon + CLI (1912 lines)
├── govori                       # Shell wrapper script (invokes govori.py via venv)
├── Govori.shortcut              # macOS Shortcuts automation file
├── requirements.txt           # Python dependencies
├── README.md                  # User-facing docs
├── LICENSE
├── __pycache__/               # Python bytecode cache (gitignored)
├── .venv/                     # Local Python 3.14 virtualenv
├── examples/
│   └── notes/
│       ├── plugin.yaml        # Example notes plugin manifest
│       ├── contexts.yaml      # Example context definitions
│       └── stuck.yaml        # Example stuck-task definitions
├── extras/
│   └── hud/
│       ├── status_hud.lua     # Optional Hammerspoon process-running indicator
│       └── README.md
├── .planning/
│   └── codebase/             # GSD analysis documents (this directory)
└── .claude/
    └── skills/
        └── debug-prod/        # Claude skill definitions
```

**Runtime config directory (outside repo, on user's machine):**
```
~/.config/govori/
├── config.yaml                # Base configuration (language, model, sample_rate, etc.)
├── env                        # API keys as shell exports (chmod 600)
├── .setup_done                # Sentinel file — setup wizard completed
└── plugins/
    └── <name>/                # One directory per plugin
        ├── plugin.yaml        # Required: plugin manifest
        ├── contexts.yaml      # Optional: AI classifier contexts
        └── stuck.yaml         # Optional: ongoing task links

~/.govori-notes/                 # Default note output (configurable)
    ├── {year}/{month}/        # Monthly subdirectories
    │   └── {date}_{time}_{slug}.md   # Individual note files
    └── index/
        └── recent.jsonl       # Append-only note index
```

## Directory Purposes

**`/` (root):**
- Purpose: Application source — the entire codebase is `govori.py` plus supporting files
- Key files: `govori.py` (application), `govori` (shell entry point), `requirements.txt`

**`examples/notes/`:**
- Purpose: Reference plugin configuration users can copy to `~/.config/govori/plugins/notes/`
- Contains: Fully-commented YAML files showing all available plugin fields
- Key files: `plugin.yaml`, `contexts.yaml`, `stuck.yaml`

**`extras/hud/`:**
- Purpose: Optional Hammerspoon Lua script for a persistent process-running indicator
- Contains: Standalone Lua script with no dependency on `govori.py`
- Key files: `status_hud.lua`

**`~/.config/govori/` (runtime, not in repo):**
- Purpose: Per-user configuration and plugin installation
- Generated: Partially (setup wizard creates `env`, `config.yaml`, `.setup_done`)
- Committed: No

## Key File Locations

**Entry Points:**
- `govori.py` line 1882: `__main__` block — daemon startup or note-text CLI path
- `govori.py` line 519: `cli_main()` — runs at module load, routes all CLI subcommands
- `govori` (shell script): activates `.venv` and executes `govori.py`

**Configuration:**
- `govori.py` lines 44–46: `CONFIG_DIR`, `CONFIG_FILE`, `PLUGINS_DIR` path constants
- `govori.py` lines 72–84: `load_config()` — loads and merges `~/.config/govori/config.yaml`
- `govori.py` lines 87–113: `load_plugins()` — discovers `~/.config/govori/plugins/` directories
- `~/.config/govori/config.yaml`: user base config (not in repo)
- `~/.config/govori/env`: API keys (not in repo, chmod 600)

**Core Logic:**
- `govori.py` lines 723–912: Audio capture and transcription pipeline
- `govori.py` lines 994–1127: Note classification and save pipeline
- `govori.py` lines 1129–1281: Merge-check pipeline
- `govori.py` lines 1339–1421: Predict/autocomplete mode
- `govori.py` lines 1423–1530: Global hotkey monitor (CGEventTap)

**Testing:**
- No test files present in the repository

## Naming Conventions

**Files:**
- Single snake_case `.py` file for application: `govori.py`
- Shell entry point matches project name: `govori`
- Example/config files use snake_case with `.yaml` extension

**Functions:**
- Public functions: `snake_case` (e.g., `start_recording`, `classify_note`, `save_as_note`)
- Private/internal helpers: `_snake_case` with leading underscore (e.g., `_encode_and_transcribe`, `_validate_meta`, `_find_merge_candidates`)
- CLI subcommand handlers: `cli_<subcommand>` prefix (e.g., `cli_setup`, `cli_plugin`, `cli_notes`)

**Constants/Globals:**
- Module-level constants: `UPPER_SNAKE_CASE` (e.g., `CONFIG_DIR`, `SAMPLE_RATE`, `MERGE_WINDOW_HOURS`)
- Global state variables: `lower_snake_case` (e.g., `recording`, `audio_chunks`, `note_mode`)
- Private globals: `_lower_snake_case` with leading underscore (e.g., `_state_lock`, `_anthropic_client`)

**Classes:**
- PascalCase, only one exists: `PredictController` (AppKit NSObject subclass)

**Plugin directories:**
- Short lowercase names matching plugin function (e.g., `notes`)

**Note files:**
- Pattern: `{YYYY-MM-DD}_{HHMM}_{kebab-slug}.md`
- Example: `2026-04-15_1430_work-deploy-issue.md`

## Where to Add New Code

**New operating mode (e.g., fn + new modifier combo):**
- Add modifier detection in `cg_event_callback()` (~line 1433)
- Add mode flag globals (~line 602)
- Add branch in `stop_and_transcribe()` (~line 819)
- Add HUD indicator in `set_hud()` (~line 681)

**New post-transcription pipeline:**
- Implement as a function following the `_note_pipeline_background()` pattern (~line 804)
- Use `threading.Thread(target=..., daemon=True).start()` for fire-and-forget
- Dispatch HUD updates via `NSOperationQueue.mainQueue().addOperationWithBlock_`

**New CLI subcommand:**
- Add `elif positional[0] == "<name>":` branch in `cli_main()` (~line 519)
- Implement as `cli_<name>(args)` function
- Handle `sys.exit(0)` after execution

**New plugin field:**
- Add loading in `load_plugins()` (~line 87)
- Surface in `build_notes_config()` or new build function (~line 129)
- Access via `NOTES_CFG` global

**Utilities:**
- Add helper functions as `_snake_case` near the logical group they belong to
- Config helpers: near line 50
- Note I/O helpers: near line 1048
- Audio helpers: near line 762

## Special Directories

**`.venv/`:**
- Purpose: Python 3.14 virtual environment with all dependencies
- Generated: Yes (`python3 -m venv .venv`)
- Committed: No

**`__pycache__/`:**
- Purpose: Python bytecode cache
- Generated: Yes (automatically by Python)
- Committed: No

**`.planning/codebase/`:**
- Purpose: GSD codebase analysis documents consumed by `/gsd-plan-phase` and `/gsd-execute-phase`
- Generated: Yes (by GSD tooling)
- Committed: Yes

**`~/.config/govori/` (runtime):**
- Purpose: All user configuration and installed plugins; persists across govori updates
- Generated: Yes (by `cli_setup()` wizard)
- Committed: No (outside repo)

---

*Structure analysis: 2026-04-15*
