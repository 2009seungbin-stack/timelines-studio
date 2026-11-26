"""Tests use a temporary database and a dedicated video root (must sit below ultradedit/research for the
retention tool). The test video root is removed after the session; nothing else is touched."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="timelines_test_"))
TEST_VIDEOS = ROOT.parent / "research" / "timelines_videos" / "_pytest_runs"
os.environ["TIMELINES_DB"] = str(_TMP / "test.db")
os.environ["TIMELINES_VIDEO_ROOT"] = str(TEST_VIDEOS)
sys.path.insert(0, str(ROOT / "backend"))


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TEST_VIDEOS, ignore_errors=True)
    shutil.rmtree(_TMP, ignore_errors=True)
