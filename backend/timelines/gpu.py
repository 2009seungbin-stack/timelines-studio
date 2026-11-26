"""Workspace-wide GPU serialization (ultradedit gpu_lock: one GPU job at a time, honours GPU_PAUSE)."""
from __future__ import annotations

import contextlib
import sys

from . import config


def clear_dead_timelines_lock() -> bool:
    """Remove E:/Flagship_work/gpu.lock only if a TIMELINES job wrote it and that process is gone
    (a job killed mid-render cannot release the lock; gpu_lock itself waits 3 h before calling it stale).
    Locks written by other workflows are never touched."""
    import os
    from pathlib import Path
    lock = Path("E:/Flagship_work/gpu.lock")
    try:
        label, pid, _ = lock.read_text("utf-8").split("|")
    except (OSError, ValueError):
        return False
    if not label.startswith("timelines"):
        return False
    try:
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))   # QUERY_LIMITED_INFORMATION
        if handle:
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            if code.value == 259:                                           # STILL_ACTIVE
                return False
    except (AttributeError, ValueError):
        return False
    lock.unlink(missing_ok=True)
    print(f"[timelines] removed stale GPU lock of dead process {pid} ({label})", file=sys.stderr)
    return True


@contextlib.contextmanager
def gpu_slot(label: str):
    clear_dead_timelines_lock()
    sys.path.insert(0, str(config.GPU_LOCK_DIR))
    try:
        from gpu_lock import gpu_slot as _slot  # type: ignore
    except ImportError:  # lock helper missing: run unlocked but say so in the log
        print(f"[timelines] gpu_lock unavailable; running {label} without workspace lock", file=sys.stderr)
        yield
        return
    with _slot(label):
        yield
