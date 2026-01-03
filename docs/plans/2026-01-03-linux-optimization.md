# Linux Optimization (inotify + persistent tmux) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce CPU usage and latency by switching log readers from sleep polling to inotify events (opt-in), and by reducing tmux subprocess count with optional persistent control-mode connection.

**Architecture:** Introduce a small `FileChangeWaiter` abstraction with an inotify-based implementation (Linux) plus an adaptive-poll fallback. Wire it into `CodexLogReader`, `GeminiLogReader`, and `OpenCodeLogReader` wait loops. For tmux, add a small `TmuxCommandRunner` to batch commands, and an optional `TmuxControlClient` to keep a single tmux client process alive.

**Tech Stack:** Python stdlib + Linux inotify via `inotify_simple` when available (fallback to `ctypes` wrapper), pytest for tests.

---

### Task 1: File watching abstraction

**Files:**
- Create: `lib/fs_watch.py`
- Test: `tests/test_fs_watch.py`

**Step 1: Write failing tests**
- Assert an inotify waiter wakes up on file append.
- Assert it wakes up on atomic file replacement (write tmp + rename).
- Assert overflow is treated as “changed” (unit-test by injecting a fake backend).

Run: `pytest -q tests/test_fs_watch.py`
Expected: FAIL (module/methods missing).

**Step 2: Implement minimal inotify waiter**
- Feature flag `CCB_INOTIFY=1` (default off).
- Linux-only enablement; gracefully fallback on import/add-watch failures.
- Watch both the file (append) and its parent dir (replacement).
- Detect and surface `IN_Q_OVERFLOW`.

**Step 3: Add adaptive polling fallback**
- Backoff when idle, reset on change.

Run: `pytest -q tests/test_fs_watch.py`
Expected: PASS.

---

### Task 2: Integrate inotify into log readers

**Files:**
- Modify: `lib/codex_comm.py`
- Modify: `lib/gemini_comm.py`
- Modify: `lib/opencode_comm.py`
- Test: `tests/test_log_watch_integration.py`

**Step 1: Write failing integration tests**
- Use temp files/dirs and small “reader-like” loops to validate wait behavior without real providers.
- Validate fallback path when inotify disabled.

Run: `pytest -q tests/test_log_watch_integration.py`
Expected: FAIL.

**Step 2: Implement wiring**
- `CodexLogReader`: wait on current log file for append; keep existing rescan timer for rotation.
- `GeminiLogReader`: watch chats dir + current session file.
- `OpenCodeLogReader`: watch current `ses_*.json` session file (and parent dir).

Run: `pytest -q tests/test_log_watch_integration.py`
Expected: PASS.

---

### Task 3: Tmux subprocess reduction + persistent control mode (optional)

**Files:**
- Modify: `lib/terminal.py`
- Test: `tests/test_tmux_backend.py`
- Docs: `README.md`

**Step 1: Write failing tests**
- Assert short send uses a single `tmux` invocation (batched `send-keys` + `Enter`).
- Assert paste path batches `paste-buffer` + `Enter` + `delete-buffer` (and uses `/dev/shm` temp file on Linux when configured).
- Assert persistent mode uses a single long-lived `Popen` (mocked) and does not spawn per send.

Run: `pytest -q tests/test_tmux_backend.py`
Expected: FAIL.

**Step 2: Implement batching runner**
- Build `tmux <cmd1> ; <cmd2> ; ...` argument list.
- Keep behavior identical.

**Step 3: Implement persistent control-mode client**
- Feature flag `CCB_TMUX_PERSIST=1` (default off).
- Spawn `tmux -C` once per process; background thread drains stdout/stderr.
- On failure, automatically fall back to non-persistent runner.

Run: `pytest -q tests/test_tmux_backend.py`
Expected: PASS.

**Step 4: Add benchmark helper**
- Script to spam N sends and report p50/p95 wall time + rough CPU (via `resource` on Unix).

---

### Task 4: Documentation + verification

**Files:**
- Modify: `README.md`
- Modify: `TODO_OPTIMIZATION.md`

**Step 1: Document new env vars**
- `CCB_INOTIFY`
- `CCB_TMUX_PERSIST`

**Step 2: Verify**
Run: `pytest -q`
Expected: PASS.

