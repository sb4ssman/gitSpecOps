"""
gh_common
=========

Shared primitives for the GitHub org duplicator: where run files live, the print lock
that keeps parallel output readable, the one subprocess wrapper every other module uses,
and small console helpers. No GitHub knowledge lives here.
"""

import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
RUNS_DIR = TOOL_DIR / "runs"
PRINT_LOCK = threading.Lock()

# Force UTF-8 so the ✓/✗/→ glyphs and non-ASCII repo names survive on Windows consoles.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def run_command(cmd, check=True, capture=True):
    """Run a shell command and return the CompletedProcess."""
    result = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        encoding='utf-8',
        errors='replace',  # replace problematic chars rather than crash on decode
        check=False
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result


def log_message(message, log_file):
    """Print to console and append a timestamped line to a log file (thread-safe)."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    with PRINT_LOCK:
        print(message)
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry + '\n')


def prompt_input(prompt):
    """Read interactive input, ignoring VS Code auto-activation noise."""
    while True:
        value = input(prompt).strip()
        lowered = value.lower()
        if lowered.endswith(r"\scripts\activate.bat") or lowered.endswith("/bin/activate"):
            print("Ignoring terminal activation command; please enter your choice.")
            continue
        return value


def format_size(kb):
    """Format size in KB to a human readable string."""
    if kb < 1024:
        return f"{kb} KB"
    elif kb < 1024 * 1024:
        return f"{kb/1024:.1f} MB"
    else:
        return f"{kb/(1024*1024):.1f} GB"
