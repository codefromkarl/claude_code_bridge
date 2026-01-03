"""CCB configuration for Windows/WSL backend environment"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_backend_env() -> str | None:
    """Get BackendEnv from env var or .ccb-config.json"""
    v = (os.environ.get("CCB_BACKEND_ENV") or "").strip().lower()
    if v in {"wsl", "windows"}:
        return v
    path = Path.cwd() / ".ccb-config.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            v = (data.get("BackendEnv") or "").strip().lower()
            if v in {"wsl", "windows"}:
                return v
        except Exception:
            pass
    return "windows" if sys.platform == "win32" else None


def _wsl_probe_distro_and_home() -> tuple[str, str]:
    """Probe default WSL distro and home directory"""
    try:
        r = subprocess.run(
            ["wsl.exe", "-e", "sh", "-lc", "echo $WSL_DISTRO_NAME; echo $HOME"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
        )
        if r.returncode == 0:
            lines = r.stdout.strip().split("\n")
            if len(lines) >= 2:
                return lines[0].strip(), lines[1].strip()
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["wsl.exe", "-l", "-q"],
            capture_output=True, text=True, encoding="utf-16-le", errors="replace", timeout=5
        )
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                distro = line.strip().strip("\x00")
                if distro:
                    break
            else:
                distro = "Ubuntu"
        else:
            distro = "Ubuntu"
    except Exception:
        distro = "Ubuntu"
    try:
        r = subprocess.run(
            ["wsl.exe", "-d", distro, "-e", "sh", "-lc", "echo $HOME"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5
        )
        home = r.stdout.strip() if r.returncode == 0 else "/root"
    except Exception:
        home = "/root"
    return distro, home


def apply_backend_env() -> None:
    """Apply BackendEnv=wsl settings (set session root paths for Windows to access WSL)"""
    if sys.platform != "win32" or get_backend_env() != "wsl":
        return
    if os.environ.get("CODEX_SESSION_ROOT") and os.environ.get("GEMINI_ROOT"):
        return
    distro, home = _wsl_probe_distro_and_home()
    for base in (fr"\\wsl.localhost\{distro}", fr"\\wsl$\{distro}"):
        prefix = base + home.replace("/", "\\")
        codex_path = prefix + r"\.codex\sessions"
        gemini_path = prefix + r"\.gemini\tmp"
        if Path(codex_path).exists() or Path(gemini_path).exists():
            os.environ.setdefault("CODEX_SESSION_ROOT", codex_path)
            os.environ.setdefault("GEMINI_ROOT", gemini_path)
            return
    prefix = fr"\\wsl.localhost\{distro}" + home.replace("/", "\\")
    os.environ.setdefault("CODEX_SESSION_ROOT", prefix + r"\.codex\sessions")
    os.environ.setdefault("GEMINI_ROOT", prefix + r"\.gemini\tmp")


def get_bool_env(name: str, default: bool = False) -> bool:
    """Get boolean value from environment variable"""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def get_int_env(name: str, default: int = 0) -> int:
    """Get integer value from environment variable"""
    try:
        return int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


def get_str_env(name: str, default: str = "") -> str:
    """Get string value from environment variable"""
    return os.environ.get(name, default)


def can_notify() -> bool:
    """Check if notifications can be sent (DISPLAY/WAYLAND_DISPLAY present and notify-send available)"""
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    if not shutil.which("notify-send"):
        return False
    return True


def send_notification(title: str, message: str) -> None:
    """Send desktop notification if enabled and available"""
    if not get_bool_env("CCB_NOTIFY", False):
        return
    if not can_notify():
        return
    try:
        subprocess.run(
            ["notify-send", "-a", "CCB", title, message],
            check=False,
            timeout=2,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        pass
