#!/usr/bin/env python3
"""
Mailbox hybrid mode helpers.

When enabled, large prompts are written to a temporary file and a short pointer
prompt is injected via terminal instead.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "y", "on"):
        return True
    if value in ("0", "false", "no", "n", "off"):
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except Exception:
        return default
    return max(0, value)


def mailbox_enabled() -> bool:
    return _env_bool("CCB_MAILBOX", default=False)


def mailbox_threshold() -> int:
    return _env_int("CCB_MAILBOX_THRESHOLD", default=500)


def mailbox_ttl_seconds() -> int:
    # TTL is a safety-net for crashed sessions; on-success deletion is preferred.
    return _env_int("CCB_MAILBOX_TTL_SECONDS", default=6 * 60 * 60)


def mailbox_tmp_dir() -> Path:
    # Spec asks for ~/.cache/ccb/tmp.
    return (Path.home() / ".cache" / "ccb" / "tmp").expanduser()


def cleanup_mailbox_tmp(dir_path: Optional[Path] = None, ttl_seconds: Optional[int] = None, now: Optional[float] = None) -> int:
    tmp_dir = (dir_path or mailbox_tmp_dir()).expanduser()
    ttl = mailbox_ttl_seconds() if ttl_seconds is None else max(0, int(ttl_seconds))
    now_ts = time.time() if now is None else float(now)
    if ttl == 0:
        return 0
    if not tmp_dir.exists():
        return 0

    removed = 0
    try:
        candidates = list(tmp_dir.glob("instruction_*.md"))
    except Exception:
        return 0

    for path in candidates:
        try:
            stat = path.stat()
        except OSError:
            continue
        age = now_ts - float(stat.st_mtime)
        if age <= ttl:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue

    return removed


def write_mailbox_instruction(content: str, dir_path: Optional[Path] = None) -> Path:
    tmp_dir = (dir_path or mailbox_tmp_dir()).expanduser()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(tmp_dir, 0o700)
    except Exception:
        pass

    cleanup_mailbox_tmp(tmp_dir)

    payload = content if isinstance(content, str) else str(content)
    for _ in range(5):
        filename = f"instruction_{time.time_ns()}.md"
        path = tmp_dir / filename
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            try:
                path.unlink()
            except Exception:
                pass
            raise

        return path.absolute()

    raise RuntimeError("Failed to allocate mailbox instruction file (too many collisions)")


def build_mailbox_prompt(path: Path) -> str:
    abs_path = Path(path).expanduser().absolute()
    return f"Please read and execute instructions from: {abs_path}"


def looks_like_cannot_read_file(reply: str) -> bool:
    if not reply:
        return False
    text = reply.strip().lower()
    needles = (
        "cannot access",
        "can't access",
        "can not access",
        "cannot read",
        "can't read",
        "can not read",
        "cannot open",
        "can't open",
        "file not found",
        "no such file",
        "does not exist",
        "permission denied",
        "无法读取",
        "不能读取",
        "无法访问",
        "不能访问",
        "找不到文件",
        "文件不存在",
        "权限不足",
    )
    return any(n in text for n in needles)

