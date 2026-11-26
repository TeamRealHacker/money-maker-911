"""Test-session safeguards.

CI only produces a pass/fail for a job, so a Windows-only difference can keep a job red with no
usable signal. Every test that depends on host behaviour (the stubbed `colab` binary, ffmpeg
availability, pygame video/audio drivers) writes a line to this log; the workflow uploads it as an
artifact, which turns the next failing run from guesswork into a name.
"""
import os
import platform
import shutil
import sys
import time
from pathlib import Path

import pytest

START = time.time()
LOG = os.environ.get("MM911_TEST_LOG")


def _write(line: str) -> None:
    if not LOG:
        return
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _describe_host() -> str:
    return (f"{platform.platform()} | python {sys.version.split()[0]} | os.name={os.name} | "
            f"timeout={os.environ.get('PYTEST_TIMEOUT', '-')} | "
            f"SELFTEST={'ok' if os.environ.get('MM911_SELFTEST') == '1' else 'n/a'}")


def pytest_configure(config):
    _write(f"[configure] {_describe_host()}")
    _write(f"[configure] colab on PATH: {shutil.which('colab')!r} | PATH[0]={os.environ.get('PATH', '')[:120]!r}")


def pytest_runtest_logreport(report):
    if report.outcome == "failed":
        _write(f"[FAILED] {report.nodeid} ({report.when})")
        if report.longreprtext:
            for line in report.longreprtext.splitlines()[-12:]:
                _write("    " + line)
    elif report.when == "call" and os.environ.get("MM911_TEST_LOG_ALL") == "1":
        _write(f"[ok] {report.nodeid}")


def pytest_sessionfinish(session, exitstatus):
    _write(f"[finish] exitstatus={exitstatus} elapsed={time.time() - START:.1f}s host={_describe_host()}")


@pytest.fixture(autouse=True)
def _mm911_repro_line(request):
    """Record the inputs every test ran with, so a host-specific failure can be reproduced."""
    yield
