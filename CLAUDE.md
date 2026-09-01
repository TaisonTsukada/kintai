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
uv run pytest tests/test_manager.py::test_function_name
```

## Architecture

This is a small CLI tool built with Click, laid out as a package under `src/kintai/`:

- `manager.py` — `KintaiManager`, the business-logic class. All commands go through it.
- `cli.py` — Click command handlers. Thin wrappers that call into `KintaiManager` and print `ClockResult`/`get_today_status()` output.
- `models.py` — `ClockResult`, the dataclass returned by clock-in/out/break/edit operations.
- `formatters.py` — console/Markdown rendering for `summary`/`week`.
- `web/` — Flask app for `kintai web` (see below). Optional client on top of `KintaiManager`; contains no business logic of its own.

**Key classes:**
- `KintaiManager` — core class managing in-memory records (`self.records: Dict[str, Dict]`) and JSON persistence
- `ClockResult` — dataclass returned by clock-in/out operations

**Data flow:**
1. `KintaiManager.__init__` loads `~/.kintai/records.json` into `self.records` (dict keyed by `YYYY-MM-DD` date strings)
2. Commands mutate `self.records` in memory
3. `save_to_file()` serializes back to JSON

**Data directory override:** The data path can be overridden via the `KINTAI_DATA_DIR` environment variable or by passing `data_dir` to `KintaiManager`. Tests use this to avoid touching `~/.kintai`.

**Timezone:** All times are stored as timezone-aware `datetime` objects in JST (`Asia/Tokyo`). Use `KintaiManager.JST` constant throughout.

**Cross-midnight shift detection:** `_find_open_session()` looks back up to `SEARCH_DAYS_BACK` (3) days to find an open session (a session with `check_in` but no `check_out`) across all records, enabling overnight shifts. Normally at most one session is open at a time — this invariant is what `clock_in`/`clock_out`/`break_start`/`break_end`/`get_today_status` rely on. It can be violated via the forgotten-clockout override (`clock_in(force=True)` after confirming "yesterday's clock-out is missing, record anyway?"), which deliberately abandons the old open session and starts a new one — this is unchanged from the pre-`sessions` behavior.

## Data model: multiple sessions per day

Each date key holds `record['sessions']: List[Dict]`, not a single `check_in`/`check_out` pair. Each session is `{'check_in': datetime, 'check_out': datetime}` (the last session of a day may omit `check_out` while still open). This supports days with multiple separate work blocks (e.g. a side job worked in split shifts), not just lunch-style breaks within one continuous shift — `record['breaks']` is a separate, flat list used for pauses within whichever session is currently open.

- `clock_in`/`clock_out` (`kintai in`/`kintai out`) append/close entries in `sessions` — running `in`/`out` twice in a day produces two sessions.
- `set_day_sessions(date_str, sessions, breaks=None)` fully replaces a day's sessions/breaks in one call; this is what the web UI's save action and the CLI's `--session` option use. It allows at most one session in the list to be open (no `check_out`) — this lets a day with an in-progress session (e.g. currently clocked in on a later shift) still have its already-closed sessions edited and saved; two or more open sessions in one call is rejected.
- `edit_record(date_str, check_in_time, check_out_time, session_index=0)` edits a single session by index (defaults to the first, for backward-compatible single-session `edit --in/--out` usage).
- `_build_daily_record` returns `None` for any day with an open session (excluded from `summary`/`export`/`week` aggregates, same as the old "no check_out yet" exclusion). `get_month_days(year_month)` is the separate, non-excluding accessor used by the web UI — it returns every calendar day including open/in-progress ones, since that's exactly what a "quick fix" screen needs to show.

**JSON migration:** Old records (`version: '1.0.0'`, single `check_in`/`check_out` per date) are migrated automatically on load into the `sessions` list format (`version: '2.0.0'`) via `_migrate_entry()` in `manager.py`. The first time a migration happens, the original file is backed up once to `records.json.v1.bak` before being overwritten.

## Web UI (`kintai web`)

`kintai web` starts a local Flask server (`src/kintai/web/app.py`) and opens a browser showing a monthly attendance table with inline editing (add/edit/remove sessions and breaks per day, including overnight sessions via a "翌日" toggle). 画面上部には月次サマリー（勤務日数・総勤務時間・総休憩時間・実勤務時間・平均勤務時間・平均実勤務時間）を表示する。これは `get_monthly_summary` の結果をそのまま描画したもので、CLI の `kintai summary` と同じ数値になる — つまり進行中セッションのある日は集計から除外される（表には行が出ているのに合計に含まれないため、そういう日があるときだけ「進行中のセッションがある日は集計に含まれません」の注記を出す）。残業/不足は所定労働時間の前提が必要なので Web には出していない（CLI の `summary --work-hours` のみ）。

It is a thin client: all routes call `KintaiManager` methods (`get_month_days`, `get_monthly_summary`, `set_day_sessions`) and contain no independent business logic. Flask is a regular dependency (not optional) since this is a primary feature of the tool. `use_reloader=False` is required in `app.run()` — the reloader re-execs the process and breaks both Ctrl+C handling and the auto-opened browser tab.

## Break lock (`kintai break`)

`kintai break` with no subcommand starts a break and blocks the foreground process (a simple `time.sleep` loop) until `Ctrl+C`, at which point it ends the break and exits — useful as a "the terminal is locked while I'm on break" workflow. The scripted, non-blocking `kintai break start` / `kintai break end` subcommands still exist for non-interactive use. The blocking wait is factored into a module-level `_wait_forever()` in `cli.py` specifically so tests can monkeypatch it to raise `KeyboardInterrupt` — `click.testing.CliRunner` cannot simulate a real Ctrl+C.
