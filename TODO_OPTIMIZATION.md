# CCB Optimization Plan (Linux & Core Interaction)

> **Execution Notes / Definition of Done**
>
> For each checkbox item below, aim to include:
> - **Scope:** affected backends/platforms (tmux / WezTerm / iTerm2 / WSL / Linux native).
> - **Success Metrics:** measurable target (latency, CPU, failure rate) and how to observe it.
> - **Feature Flag:** env toggle + safe default-off rollout path.
> - **Fallback & Rollback:** what happens when dependency/feature is missing or fails.
> - **Verification:** a minimal reproducible manual script (and a test if feasible).

## 1. Linux Platform Deep Optimization (Linux 深度优化)

### 1.1 Performance (性能)
- [x] **Implement `inotify` for File Watching**
  - **Goal:** Replace `time.sleep` polling with real-time kernel events to reduce latency and CPU usage.
  - **Action:**
    - Detect Linux environment.
    - Prefer `inotify_simple` (lightweight Python dependency) or `watchdog` (optional) to monitor:
      - Session files like `.codex-session` / `.gemini-session` (project root)
      - Gemini chat directories under `~/.gemini/tmp/<hash>/chats` (directory watch is safer than single-file watch)
    - Handle edge cases:
      - File replacement/rotation (watch parent dir; re-open latest session file on change)
      - Event overflow (`IN_Q_OVERFLOW`) and missed events
      - Mounted filesystems / WSL mounts where inotify may be unreliable
    - **Fallback:** polling with an adaptive interval + force-read timer (mtime granularity issues).
  - **Completed:** 2026-01-03

- [x] **Persistent Tmux Connection (Control Mode)**
  - **Goal:** Eliminate process forking overhead for high-frequency interactions.
  - **Action:**
    - First attempt a low-risk win: reduce subprocess count by batching tmux commands (single `tmux` invocation with `\;`) where possible.
    - If still bottlenecked, explore maintaining a persistent connection (e.g., `libtmux` server) instead of spawning `tmux` for every `send-keys`/buffer op.
    - Use `/dev/shm` (Linux) for temporary IPC files (locks/FIFOs) when available; fallback to runtime dir.
    - **Success Metrics:** p50/p95 end-to-end send latency and CPU usage while spamming short commands.
  - **Completed:** 2026-01-03

### 1.2 User Experience (用户体验)
- [ ] **Desktop Notification Integration**
  - **Goal:** Notify users when long-running background tasks (`/cask`, `/gask`) complete.
  - **Action:**
    - Detect `DISPLAY` or `WAYLAND_DISPLAY` env vars.
    - If `notify-send` exists, invoke `notify-send` "Task Completed" with a snippet of the result upon detecting "completed" signal in session logs.
    - **Feature Flag:** `CCB_NOTIFY=1` (default off).
    - **Fallback:** no-op if headless or missing `notify-send`.

- [ ] **Global Shortcut Generation Script**
  - **Goal:** One-key access to AI terminal overlay.
  - **Action:**
    - Create a helper script (`bin/setup-shortcuts.sh`) to generate config snippets for Gnome/KDE/i3 that bind a hotkey (e.g., `Alt+Space`) to `ccb up` or focus existing WezTerm window.
    - Keep it output-only (print snippet + instructions), no privileged writes by default.

## 2. Interaction Robustness & Logic (交互严谨性与逻辑)

### 2.1 "Mailbox" Hybrid Mode (混合信箱模式) - **High Priority**
- **Goal:** Solve terminal paste instability (truncation, garbled text) for long content without increasing token costs significantly.
- **Strategy:** Route content based on length.
  - **Short (<500 chars):** Direct terminal injection (current method).
  - **Long (>500 chars):** File-based transfer.
- **Action:**
  - [x] Implement `Threshold Check` in `DualBridge` and `GeminiCommunicator` (and other providers if applicable).
  - [x] Create `_send_via_file` method:
    1. Write content to `.ccb/tmp/instruction_<timestamp>.md`.
       - Prefer a per-session temp dir (runtime dir or `~/.cache/ccb/tmp/<session_id>`); keep permissions restrictive.
    2. Construct prompt: `Please read and execute instructions from: <abs_path>`.
    3. Send short prompt via terminal.
  - [x] Implement auto-cleanup for temp instruction files (TTL + size cap + on-success delete).
  - **Feature Flags:**
    - `CCB_MAILBOX=1` (default off)
    - `CCB_MAILBOX_THRESHOLD=500`
    - `CCB_MAILBOX_TTL_SECONDS=21600` (6 hours)
  - **Verification:**
  - [x] Send a multi-paragraph prompt and confirm no truncation/garbling across tmux and WezTerm modes.
  - [x] Confirm behavior when provider cannot read local files (must gracefully fallback to terminal send).
  - **Implementation:**
    - `lib/mailbox.py` (158 lines) - Core helper module
    - `lib/codex_dual_bridge.py` - Integration for DualBridge
    - `lib/gemini_comm.py` - Integration for GeminiCommunicator
    - `lib/opencode_comm.py` - Integration for OpenCodeCommunicator
    - `tests/test_mailbox.py` - Unit tests (passing)
  - **Completed:** 2026-01-03

### 2.2 Context Synchronization (上下文同步)
- [x] **Auto-CWD Sync**
  - **Goal:** Prevent AI from executing commands in wrong directory after user switches shell CWD.
  - **Action:**
    - Decide on direction explicitly: sync target AI session CWD to the caller's `PWD` (opt-in).
    - Before sending a prompt, compare session's last known `work_dir` (from session file) with current shell `PWD`.
    - If mismatched and enabled, inject a `cd <PWD>` command *only when safe* (e.g., `PWD` exists, not empty).
    - **Feature Flag:** `CCB_AUTO_CWD_SYNC=1` (default off).
    - **Fallback:** do nothing; include a warning in verbose mode.
  - **Implementation:**
    - `lib/codex_comm.py` - `_handle_auto_cwd()` + persistence in `_remember_codex_session()`
    - `lib/gemini_comm.py` - `_handle_auto_cwd()` + persistence in `_remember_gemini_session()`
    - `lib/opencode_comm.py` - `_handle_auto_cwd()` + `_remember_opencode_session()`
    - `tests/test_codex_session_health.py` - Session health check test (passing)
  - **Completed:** 2026-01-03

### 2.3 Safety & Error Handling (安全与错误处理)
- [ ] **Bracketed Paste Enforcement**
  - **Goal:** Prevent shell injection attacks or misinterpretation of special chars (newlines, tabs).
  - **Action:**
    - Enforce bracketed paste for multiline/long/unsafe payloads by default.
    - Keep single-line fast-path for UX when needed (e.g., avoiding "[Pasted Content ...]" in some TUIs).
    - **Feature Flag:** `CCB_FORCE_PASTE=1` to force paste mode for all injections (default off).

- [ ] **Error Snapshot (Screen Capture)**
  - **Goal:** meaningful error messages instead of generic "Timeout".
  - **Action:**
    - On `cask-w`/`gask-w` timeout: call `tmux capture-pane` or `wezterm cli get-text`.
    - Extract last 10-20 lines of the backend terminal.
    - Display this "screenshot" to user to reveal blocked prompts (e.g., "Overwrite? y/n").
    - **Fallback:** if snapshot fails, include the last known log markers and a suggestion to manually open the pane.
    - **Safety:** consider redacting secrets (tokens) if snapshot is shown in logs.

## 3. Architecture Refactoring (架构重构)

### 3.1 Abstraction
- [ ] **Provider Interface (Strategy Pattern)**
  - **Goal:** Simplify adding new models (e.g., DeepSeek, Opencode) and reduce duplicate logic.
  - **Action:**
    - Create `BaseProvider` class with abstract methods (`send`, `read`, `health_check`).
    - Add `capabilities()` (or similar) to drive routing decisions (mailbox/file-read support, paste mode preference, max safe injection length, snapshot support).
    - Refactor Codex/Gemini/Opencode to inherit from it.

- [ ] **Unified Config Manager**
  - **Goal:** Centralize hardcoded paths, timeouts, and env var parsing.
  - **Action:**
    - Expand `ccb_config.py` to be single source of truth for all configuration (timeouts, paths, thresholds, feature flags).
    - Document each env var with default + rationale (to keep behavior stable across platforms).
    - **Partial Implementation:** `get_bool_env()`, `get_int_env()`, `get_str_env()` added

## 4. Editor Integration (编辑器集成)

- [ ] **Unix Domain Socket (UDS) Server**
  - **Goal:** High-speed, concurrent API for editors (Neovim/VSCode) to talk to ccb.
  - **Action:**
    - Start a lightweight UDS server at `~/.cache/ccb/socket` that accepts JSON requests and routes them to the active session.
    - **Safety:** create socket with `0600` permissions, validate request schema, apply per-request timeouts, and avoid exposing arbitrary command execution by default.
