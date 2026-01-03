#!/usr/bin/env python3
"""
task_utils.py - Utility for reading task outputs from /tmp/claude
"""
import os
import subprocess
from pathlib import Path
from typing import Optional, List

def _get_claude_tmp_dir() -> Path:
    return Path("/tmp/claude")

def _transform_path_to_slug(path: Path) -> str:
    """
    Transform path to slug format used by the task runner.
    Observed behavior: / -> - and _ -> -
    Example: /home/user/my_project -> -home-user-my-project
    """
    s = str(path.resolve())
    return s.replace('/', '-').replace('_', '-')

def find_task_output_dir(work_dir: Optional[Path] = None) -> Optional[Path]:
    if work_dir is None:
        work_dir = Path.cwd()
    
    base = _get_claude_tmp_dir()
    if not base.exists():
        return None

    # Try strict slugification (replace / and _ with -)
    slug = _transform_path_to_slug(work_dir)
    candidate = base / slug
    if candidate.exists():
        return candidate

    # Fallback: maybe the directory name is slightly different?
    # We can try to list directories in base and find one that matches the pattern
    # But for now, let's rely on the observed pattern.
    
    return None

def get_latest_task_output(work_dir: Optional[Path] = None) -> Optional[str]:
    """
    Find and read the latest task output file for the current project.
    Returns the content string or None if not found/readable.
    """
    task_dir_parent = find_task_output_dir(work_dir)
    if not task_dir_parent:
        return None
        
    tasks_dir = task_dir_parent / "tasks"
    if not tasks_dir.exists():
        return None
        
    # Find all .output files
    try:
        files = list(tasks_dir.glob("*.output"))
    except Exception:
        return None
        
    if not files:
        return None
        
    # Sort by mtime, newest first
    try:
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return None
        
    latest_file = files[0]
    
    # Read content
    try:
        # Try python read first
        return latest_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        # Fallback to cat (as requested for special path characters handling)
        try:
            return subprocess.check_output(
                ["cat", str(latest_file)], 
                stderr=subprocess.DEVNULL
            ).decode("utf-8", errors="replace")
        except Exception:
            return None
