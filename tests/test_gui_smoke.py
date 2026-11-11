"""Run the offscreen Qt smoke tests in a dedicated subprocess.

PySide6 on Windows can crash while finalizing Qt objects after pytest has
already printed a passing summary. Keeping Qt out of the main pytest process
makes that boundary explicit: the child prints its own summary and exits with
pytest's real code; the parent diagnoses failures from the child output.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPL = Path(__file__).with_name("gui_smoke_impl.py")


def test_gui_smoke_in_subprocess():
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    # The child runs pytest in-process, prints its summary, then hard-exits
    # with pytest's actual code. The hard exit is scoped to this Qt child only;
    # the parent process keeps normal pytest cleanup and failure reporting.
    code = (
        "import os, sys, pytest; "
        f"rc = pytest.main(['-q', '-p', 'no:cacheprovider', r'{IMPL}']); "
        "sys.stdout.flush(); sys.stderr.flush(); os._exit(int(rc))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )
    assert proc.returncode == 0, (
        f"GUI subprocess failed ({proc.returncode})\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
