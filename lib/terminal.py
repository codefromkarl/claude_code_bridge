#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(0.0, value)


def is_windows() -> bool:
    return platform.system() == "Windows"


def is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except Exception:
        return False


def _load_cached_wezterm_bin() -> str | None:
    """Load cached WezTerm path from installation"""
    config = Path.home() / ".config/ccb/env"
    if config.exists():
        try:
            for line in config.read_text().splitlines():
                if line.startswith("CODEX_WEZTERM_BIN="):
                    path = line.split("=", 1)[1].strip()
                    if path and Path(path).exists():
                        return path
        except Exception:
            pass
    return None


_cached_wezterm_bin: str | None = None


def _get_wezterm_bin() -> str | None:
    """Get WezTerm path (with cache)"""
    global _cached_wezterm_bin
    if _cached_wezterm_bin:
        return _cached_wezterm_bin
    # Priority: env var > install cache > PATH > hardcoded paths
    override = os.environ.get("CODEX_WEZTERM_BIN") or os.environ.get("WEZTERM_BIN")
    if override and Path(override).exists():
        _cached_wezterm_bin = override
        return override
    cached = _load_cached_wezterm_bin()
    if cached:
        _cached_wezterm_bin = cached
        return cached
    found = shutil.which("wezterm") or shutil.which("wezterm.exe")
    if found:
        _cached_wezterm_bin = found
        return found
    if is_wsl():
        for drive in "cdefghijklmnopqrstuvwxyz":
            for path in [f"/mnt/{drive}/Program Files/WezTerm/wezterm.exe",
                         f"/mnt/{drive}/Program Files (x86)/WezTerm/wezterm.exe"]:
                if Path(path).exists():
                    _cached_wezterm_bin = path
                    return path
    return None


def _is_windows_wezterm() -> bool:
    """Detect if WezTerm is running on Windows"""
    override = os.environ.get("CODEX_WEZTERM_BIN") or os.environ.get("WEZTERM_BIN")
    if override:
        if ".exe" in override.lower() or "/mnt/" in override:
            return True
    if shutil.which("wezterm.exe"):
        return True
    if is_wsl():
        for drive in "cdefghijklmnopqrstuvwxyz":
            for path in [f"/mnt/{drive}/Program Files/WezTerm/wezterm.exe",
                         f"/mnt/{drive}/Program Files (x86)/WezTerm/wezterm.exe"]:
                if Path(path).exists():
                    return True
    return False


def _default_shell() -> tuple[str, str]:
    if is_wsl():
        return "bash", "-c"
    if is_windows():
        for shell in ["pwsh", "powershell"]:
            if shutil.which(shell):
                return shell, "-Command"
        return "powershell", "-Command"
    return "bash", "-c"


def get_shell_type() -> str:
    if is_windows() and os.environ.get("CCB_BACKEND_ENV", "").lower() == "wsl":
        return "bash"
    shell, _ = _default_shell()
    if shell in ("pwsh", "powershell"):
        return "powershell"
    return "bash"


class TerminalBackend(ABC):
    @abstractmethod
    def send_text(self, pane_id: str, text: str) -> None: ...
    @abstractmethod
    def is_alive(self, pane_id: str) -> bool: ...
    @abstractmethod
    def kill_pane(self, pane_id: str) -> None: ...
    @abstractmethod
    def activate(self, pane_id: str) -> None: ...
    @abstractmethod
    def create_pane(self, cmd: str, cwd: str, direction: str = "right", percent: int = 50, parent_pane: Optional[str] = None) -> str: ...
    @abstractmethod
    def capture_pane(self, pane_id: str, lines: int = 20) -> Optional[str]: ...


class TmuxRunner:
    def run_batched(self, cmds: list[list[str]], *, check: bool = True) -> None: ...


class SubprocessTmuxRunner(TmuxRunner):
    def run_batched(self, cmds: list[list[str]], *, check: bool = True) -> None:
        if not cmds:
            return
        argv: list[str] = ["tmux"]
        for idx, cmd in enumerate(cmds):
            if idx:
                argv.append(";")
            argv.extend(cmd)
        subprocess.run(argv, check=check)


class TmuxControlClient(TmuxRunner):
    """
    Persistent tmux client using control mode (`tmux -C`).

    This avoids spawning a new `tmux` process per operation; it's best-effort and falls back to
    subprocess mode on any failure.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._proc = subprocess.Popen(
            ["tmux", "-C"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    def is_alive(self) -> bool:
        return self._proc.poll() is None

    def close(self) -> None:
        with self._lock:
            if self._proc.poll() is not None:
                return
            try:
                self._proc.terminate()
            except Exception:
                pass
        try:
            self._proc.wait(timeout=0.2)
        except Exception:
            pass

    @staticmethod
    def _format_cmd(args: list[str]) -> str:
        return " ".join(shlex.quote(a) for a in args)

    def run_batched(self, cmds: list[list[str]], *, check: bool = True) -> None:
        if not cmds:
            return
        if self._proc.poll() is not None:
            raise RuntimeError("tmux control client not running")
        if not self._proc.stdin:
            raise RuntimeError("tmux control client has no stdin")

        with self._lock:
            for cmd in cmds:
                line = self._format_cmd(cmd)
                self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()


class TmuxBackend(TerminalBackend):
    _control_client: "TmuxControlClient | None" = None

    @staticmethod
    def _bool_env(name: str, default: bool = False) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on")

    @classmethod
    def _tmux_tmp_dir(cls) -> Path:
        override = (os.environ.get("CCB_TMUX_TMPDIR") or "").strip()
        if override:
            base = Path(override).expanduser()
        else:
            if sys.platform == "linux":
                shm = Path("/dev/shm")
                if shm.is_dir() and os.access(str(shm), os.W_OK):
                    base = shm / "ccb"
                else:
                    base = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "ccb"
            else:
                base = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "ccb"
        base.mkdir(parents=True, exist_ok=True)
        return base

    @classmethod
    def _runner(cls) -> "TmuxRunner":
        if not cls._bool_env("CCB_TMUX_PERSIST", False):
            return SubprocessTmuxRunner()
        if cls._control_client and cls._control_client.is_alive():
            return cls._control_client
        try:
            cls._control_client = TmuxControlClient()
            return cls._control_client
        except Exception:
            cls._control_client = None
            return SubprocessTmuxRunner()

    def send_text(self, session: str, text: str) -> None:
        sanitized = text.replace("\r", "").strip()
        if not sanitized:
            return
        force_paste = os.environ.get("CCB_FORCE_PASTE", "").lower() in ("1", "true", "yes", "on")
        runner = self._runner()
        # Fast-path for typical short, single-line commands (fewer tmux subprocess calls).
        if not force_paste and "\n" not in sanitized and len(sanitized) <= 200:
            runner.run_batched(
                [
                    ["send-keys", "-t", session, "-l", sanitized],
                    ["send-keys", "-t", session, "Enter"],
                ],
                check=True,
            )
            return

        buffer_name = f"tb-{os.getpid()}-{int(time.time() * 1000)}"
        encoded = sanitized.encode("utf-8")
        tmp_file: Optional[Path] = None
        cleanup_needed = True
        try:
            tmp_dir = self._tmux_tmp_dir()
            with tempfile.NamedTemporaryFile(prefix="ccb-tmux-", suffix=".txt", dir=str(tmp_dir), delete=False) as handle:
                try:
                    os.chmod(handle.name, 0o600)
                except Exception:
                    pass
                handle.write(encoded)
                handle.flush()
                tmp_file = Path(handle.name)

            enter_delay = _env_float("CCB_TMUX_ENTER_DELAY", 0.0)
            cmds = [
                ["load-buffer", "-b", buffer_name, str(tmp_file)],
                ["paste-buffer", "-t", session, "-b", buffer_name, "-p"],
            ]
            if enter_delay <= 0:
                cmds.append(["send-keys", "-t", session, "Enter"])
                cmds.append(["delete-buffer", "-b", buffer_name])
                runner.run_batched(cmds, check=True)
                cleanup_needed = False
            else:
                runner.run_batched(cmds, check=True)
                time.sleep(enter_delay)
                runner.run_batched(
                    [
                        ["send-keys", "-t", session, "Enter"],
                        ["delete-buffer", "-b", buffer_name],
                    ],
                    check=True,
                )
                cleanup_needed = False
        finally:
            if tmp_file:
                try:
                    tmp_file.unlink(missing_ok=True)
                except Exception:
                    pass
            if cleanup_needed:
                # Best-effort cleanup if previous step failed before delete-buffer.
                try:
                    subprocess.run(["tmux", "delete-buffer", "-b", buffer_name], stderr=subprocess.DEVNULL)
                except Exception:
                    pass

    def is_alive(self, session: str) -> bool:
        result = subprocess.run(["tmux", "has-session", "-t", session], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0

    def kill_pane(self, session: str) -> None:
        subprocess.run(["tmux", "kill-session", "-t", session], stderr=subprocess.DEVNULL)

    def activate(self, session: str) -> None:
        subprocess.run(["tmux", "attach", "-t", session])

    def create_pane(self, cmd: str, cwd: str, direction: str = "right", percent: int = 50, parent_pane: Optional[str] = None) -> str:
        session_name = f"ai-{int(time.time()) % 100000}-{os.getpid()}"
        subprocess.run(["tmux", "new-session", "-d", "-s", session_name, "-c", cwd, cmd], check=True)
        return session_name

    def capture_pane(self, pane_id: str, lines: int = 20) -> Optional[str]:
        try:
            # -p: output to stdout, -S -lines: start from last N lines
            result = subprocess.run(
                ["tmux", "capture-pane", "-p", "-t", pane_id, "-S", str(-lines)],
                capture_output=True, text=True, errors="replace"
            )
            if result.returncode == 0:
                return result.stdout.rstrip()
        except Exception:
            pass
        return None


class Iterm2Backend(TerminalBackend):
    """iTerm2 backend, using it2 CLI (pip install it2)"""
    _it2_bin: Optional[str] = None

    @classmethod
    def _bin(cls) -> str:
        if cls._it2_bin:
            return cls._it2_bin
        override = os.environ.get("CODEX_IT2_BIN") or os.environ.get("IT2_BIN")
        if override:
            cls._it2_bin = override
            return override
        cls._it2_bin = shutil.which("it2") or "it2"
        return cls._it2_bin

    def send_text(self, session_id: str, text: str) -> None:
        sanitized = text.replace("\r", "").strip()
        if not sanitized:
            return
        # Similar to WezTerm: send text first, then send Enter
        # it2 session send sends text (without newline)
        subprocess.run(
            [self._bin(), "session", "send", sanitized, "--session", session_id],
            check=True,
        )
        # Wait a bit for TUI to process input
        time.sleep(0.01)
        # Send Enter key (using \r)
        subprocess.run(
            [self._bin(), "session", "send", "\r", "--session", session_id],
            check=True,
        )

    def is_alive(self, session_id: str) -> bool:
        try:
            result = subprocess.run(
                [self._bin(), "session", "list", "--json"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                return False
            sessions = json.loads(result.stdout)
            return any(s.get("id") == session_id for s in sessions)
        except Exception:
            return False

    def kill_pane(self, session_id: str) -> None:
        subprocess.run(
            [self._bin(), "session", "close", "--session", session_id, "--force"],
            stderr=subprocess.DEVNULL
        )

    def activate(self, session_id: str) -> None:
        subprocess.run([self._bin(), "session", "focus", session_id])

    def create_pane(self, cmd: str, cwd: str, direction: str = "right", percent: int = 50, parent_pane: Optional[str] = None) -> str:
        # iTerm2 split: vertical corresponds to right, horizontal to bottom
        args = [self._bin(), "session", "split"]
        if direction == "right":
            args.append("--vertical")
        # If parent_pane specified, target that session
        if parent_pane:
            args.extend(["--session", parent_pane])

        result = subprocess.run(args, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace")
        # it2 output format: "Created new pane: <session_id>"
        output = result.stdout.strip()
        if ":" in output:
            new_session_id = output.split(":")[-1].strip()
        else:
            # Try to get from stderr or elsewhere
            new_session_id = output

        # Execute startup command in new pane
        if new_session_id and cmd:
            # First cd to work directory, then execute command
            full_cmd = f"cd {shlex.quote(cwd)} && {cmd}"
            time.sleep(0.2)  # Wait for pane ready
            # Use send + Enter, consistent with send_text
            subprocess.run(
                [self._bin(), "session", "send", full_cmd, "--session", new_session_id],
                check=True
            )
            time.sleep(0.01)
            subprocess.run(
                [self._bin(), "session", "send", "\r", "--session", new_session_id],
                check=True
            )

        return new_session_id
    
    def capture_pane(self, pane_id: str, lines: int = 20) -> Optional[str]:
        # it2 does not currently support capturing text from session.
        return None


class WeztermBackend(TerminalBackend):
    _wezterm_bin: Optional[str] = None

    @classmethod
    def _cli_base_args(cls) -> list[str]:
        args = [cls._bin(), "cli"]
        wezterm_class = os.environ.get("CODEX_WEZTERM_CLASS") or os.environ.get("WEZTERM_CLASS")
        if wezterm_class:
            args.extend(["--class", wezterm_class])
        if os.environ.get("CODEX_WEZTERM_PREFER_MUX", "").lower() in {"1", "true", "yes", "on"}:
            args.append("--prefer-mux")
        if os.environ.get("CODEX_WEZTERM_NO_AUTO_START", "").lower() in {"1", "true", "yes", "on"}:
            args.append("--no-auto-start")
        return args

    @classmethod
    def _bin(cls) -> str:
        if cls._wezterm_bin:
            return cls._wezterm_bin
        found = _get_wezterm_bin()
        cls._wezterm_bin = found or "wezterm"
        return cls._wezterm_bin

    def _send_enter(self, pane_id: str) -> None:
        """Send Enter key reliably using stdin (cross-platform)"""
        # Windows needs longer delay
        default_delay = 0.05 if os.name == "nt" else 0.01
        enter_delay = _env_float("CCB_WEZTERM_ENTER_DELAY", default_delay)
        if enter_delay:
            time.sleep(enter_delay)

        # Retry mechanism for reliability (Windows native occasionally drops Enter)
        max_retries = 3
        for attempt in range(max_retries):
            result = subprocess.run(
                [*self._cli_base_args(), "send-text", "--pane-id", pane_id, "--no-paste"],
                input=b"\r",
                capture_output=True,
            )
            if result.returncode == 0:
                return
            if attempt < max_retries - 1:
                time.sleep(0.05)

    def send_text(self, pane_id: str, text: str) -> None:
        sanitized = text.replace("\r", "").strip()
        if not sanitized:
            return

        has_newlines = "\n" in sanitized
        force_paste = os.environ.get("CCB_FORCE_PASTE", "").lower() in ("1", "true", "yes", "on")

        # Single-line: always avoid paste mode (prevents Codex showing "[Pasted Content ...]").
        # Use argv for short text; stdin for long text to avoid command-line length/escaping issues.
        if not has_newlines and not force_paste:
            if len(sanitized) <= 200:
                subprocess.run(
                    [*self._cli_base_args(), "send-text", "--pane-id", pane_id, "--no-paste", sanitized],
                    check=True,
                )
            else:
                subprocess.run(
                    [*self._cli_base_args(), "send-text", "--pane-id", pane_id, "--no-paste"],
                    input=sanitized.encode("utf-8"),
                    check=True,
                )
            self._send_enter(pane_id)
            return

        # Slow path: multiline or long text -> use paste mode (bracketed paste)
        subprocess.run(
            [*self._cli_base_args(), "send-text", "--pane-id", pane_id],
            input=sanitized.encode("utf-8"),
            check=True,
        )

        # Wait for TUI to process bracketed paste content
        paste_delay = _env_float("CCB_WEZTERM_PASTE_DELAY", 0.1)
        if paste_delay:
            time.sleep(paste_delay)

        self._send_enter(pane_id)

    def is_alive(self, pane_id: str) -> bool:
        try:
            result = subprocess.run([*self._cli_base_args(), "list", "--format", "json"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if result.returncode != 0:
                return False
            panes = json.loads(result.stdout)
            return any(str(p.get("pane_id")) == str(pane_id) for p in panes)
        except Exception:
            return False

    def kill_pane(self, pane_id: str) -> None:
        subprocess.run([*self._cli_base_args(), "kill-pane", "--pane-id", pane_id], stderr=subprocess.DEVNULL)

    def activate(self, pane_id: str) -> None:
        subprocess.run([*self._cli_base_args(), "activate-pane", "--pane-id", pane_id])

    def create_pane(self, cmd: str, cwd: str, direction: str = "right", percent: int = 50, parent_pane: Optional[str] = None) -> str:
        args = [*self._cli_base_args(), "split-pane"]
        force_wsl = os.environ.get("CCB_BACKEND_ENV", "").lower() == "wsl"
        use_wsl_launch = (is_wsl() and _is_windows_wezterm()) or (force_wsl and is_windows())
        if use_wsl_launch:
            in_wsl_pane = bool(os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"))
            wsl_cwd = cwd
            wsl_localhost_match = re.match(r'^[/\\]{1,2}wsl\.localhost[/\\][^/\\]+(.+)$', cwd, re.IGNORECASE)
            if wsl_localhost_match:
                wsl_cwd = wsl_localhost_match.group(1).replace('\\', '/')
            elif "\\" in cwd or (len(cwd) > 2 and cwd[1] == ":"):
                try:
                    wslpath_cmd = ["wslpath", "-a", cwd] if is_wsl() else ["wsl.exe", "wslpath", "-a", cwd]
                    result = subprocess.run(wslpath_cmd, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace")
                    wsl_cwd = result.stdout.strip()
                except Exception:
                    pass
            if direction == "right":
                args.append("--right")
            elif direction == "bottom":
                args.append("--bottom")
            args.extend(["--percent", str(percent)])
            if parent_pane:
                args.extend(["--pane-id", parent_pane])
            startup_script = f"cd {shlex.quote(wsl_cwd)} && exec {cmd}"
            if in_wsl_pane:
                args.extend(["--", "bash", "-l", "-i", "-c", startup_script])
            else:
                args.extend(["--", "wsl.exe", "bash", "-l", "-i", "-c", startup_script])
        else:
            args.extend(["--cwd", cwd])
            if direction == "right":
                args.append("--right")
            elif direction == "bottom":
                args.append("--bottom")
            args.extend(["--percent", str(percent)])
            if parent_pane:
                args.extend(["--pane-id", parent_pane])
            shell, flag = _default_shell()
            args.extend(["--", shell, flag, cmd])
        try:
            result = subprocess.run(args, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace")
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"WezTerm split-pane failed:\nCommand: {' '.join(args)}\nStderr: {e.stderr}") from e
    
    def capture_pane(self, pane_id: str, lines: int = 20) -> Optional[str]:
        try:
            # get-text --lines is not always available or behaves differently, 
            # checking help might be needed, but 'get-text' usually dumps all.
            # WezTerm CLI get-text: `wezterm cli get-text --pane-id <ID>`.
            # There is no --lines limit in older versions, but we can slice in python.
            result = subprocess.run(
                [*self._cli_base_args(), "get-text", "--pane-id", pane_id],
                capture_output=True, text=True, errors="replace"
            )
            if result.returncode == 0:
                text = result.stdout.rstrip()
                # Manually slice last N lines
                all_lines = text.splitlines()
                return "\n".join(all_lines[-lines:])
        except Exception:
            pass
        return None


_backend_cache: Optional[TerminalBackend] = None


def detect_terminal() -> Optional[str]:
    # Priority: check current env vars (already running in a terminal)
    if os.environ.get("WEZTERM_PANE"):
        return "wezterm"
    if os.environ.get("ITERM_SESSION_ID"):
        return "iterm2"
    if os.environ.get("TMUX"):
        return "tmux"
    # Check configured binary override or cached path
    if _get_wezterm_bin():
        return "wezterm"
    override = os.environ.get("CODEX_IT2_BIN") or os.environ.get("IT2_BIN")
    if override and Path(override).expanduser().exists():
        return "iterm2"
    # Check available terminal tools
    if shutil.which("it2"):
        return "iterm2"
    if shutil.which("tmux") or shutil.which("tmux.exe"):
        return "tmux"
    return None


def get_backend(terminal_type: Optional[str] = None) -> Optional[TerminalBackend]:
    global _backend_cache
    if _backend_cache:
        return _backend_cache
    t = terminal_type or detect_terminal()
    if t == "wezterm":
        _backend_cache = WeztermBackend()
    elif t == "iterm2":
        _backend_cache = Iterm2Backend()
    elif t == "tmux":
        _backend_cache = TmuxBackend()
    return _backend_cache


def get_backend_for_session(session_data: dict) -> Optional[TerminalBackend]:
    terminal = session_data.get("terminal", "tmux")
    if terminal == "wezterm":
        return WeztermBackend()
    elif terminal == "iterm2":
        return Iterm2Backend()
    return TmuxBackend()


def get_pane_id_from_session(session_data: dict) -> Optional[str]:
    terminal = session_data.get("terminal", "tmux")
    if terminal == "wezterm":
        return session_data.get("pane_id")
    elif terminal == "iterm2":
        return session_data.get("pane_id")
    return session_data.get("tmux_session")
