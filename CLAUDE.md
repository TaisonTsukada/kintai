# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run kintai <command>

# Run all tests
uv run pytest

# Run a single test
uv run pytest tests/test_kintai.py::test_function_name
```

## Architecture

This is a single-file CLI tool (`kintai.py`) built with Click. All business logic lives in the `KintaiManager` class; Click command handlers are thin wrappers that call into it.

**Key classes:**
- `KintaiManager` — core class managing in-memory records (`self.records: Dict[str, Dict]`) and JSON persistence
- `ClockResult` — dataclass returned by clock-in/out operations

**Data flow:**
1. `KintaiManager.__init__` loads `~/.kintai/records.json` into `self.records` (dict keyed by `YYYY-MM-DD` date strings)
2. Commands mutate `self.records` in memory
3. `save_to_file()` serializes back to JSON

**Data directory override:** The data path can be overridden via the `KINTAI_DATA_DIR` environment variable or by passing `data_dir` to `KintaiManager`. Tests use this to avoid touching `~/.kintai`.

**Timezone:** All times are stored as timezone-aware `datetime` objects in JST (`Asia/Tokyo`). Use `KintaiManager.JST` constant throughout.

**Cross-midnight shift detection:** `_find_open_check_in_record()` looks back up to `SEARCH_DAYS_BACK` (3) days to find an open check-in without a matching check-out, enabling overnight shifts.
