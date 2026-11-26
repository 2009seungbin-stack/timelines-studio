"""Free-memory guard: heavy steps (Blender, final encode) wait while free physical RAM is below a floor
(TIMELINES_MIN_FREE_RAM_GB, default 1 GB) instead of pushing the machine into swap/termination."""
from __future__ import annotations

import ctypes
import os
import sys
import time


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def free_gb() -> tuple[float, float]:
    """(free physical RAM, free commit) in GB; (inf, inf) where unsupported."""
    if os.name != "nt":
        return float("inf"), float("inf")
    st = _MemStatus()
    st.dwLength = ctypes.sizeof(_MemStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return st.ullAvailPhys / 1e9, st.ullAvailPageFile / 1e9


def wait_for_memory(label: str, min_gb: float | None = None, timeout_s: int = 3600, progress=None) -> float:
    floor = float(os.environ.get("TIMELINES_MIN_FREE_RAM_GB", "1")) if min_gb is None else min_gb
    t0 = time.time()
    while True:
        ram, commit = free_gb()
        if ram >= floor and commit >= floor:
            return ram
        msg = f"{label}: waiting for memory (free RAM {ram:.1f} GB, commit {commit:.1f} GB < {floor} GB)"
        print(msg, file=sys.stderr)
        if progress:
            progress(0.0, msg)
        if time.time() - t0 > timeout_s:
            raise MemoryError(msg)
        time.sleep(15)
