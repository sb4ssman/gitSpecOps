"""The release readiness gate is read-only and checks recipe assets without a build tool."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "git-sync-suggester" / "packaging"))
from release_check import _pyinstaller_available, release_checks


def test_current_checkout_has_a_parseable_desktop_recipe_gate():
    rows = dict((name, (passed, detail)) for name, passed, detail in release_checks(ROOT))
    assert rows["version"][0]
    assert rows["desktop recipe"][0]
    assert "PyInstaller" in rows


def test_release_gate_checks_the_running_python_environment_for_pyinstaller():
    with patch("release_check.importlib.util.find_spec", return_value=object()):
        assert _pyinstaller_available()
    with patch("release_check.importlib.util.find_spec", return_value=None):
        assert not _pyinstaller_available()


def main():
    test_current_checkout_has_a_parseable_desktop_recipe_gate()
    test_release_gate_checks_the_running_python_environment_for_pyinstaller()
    print("ALL-RELEASE-CHECK-TESTS-PASS")


if __name__ == "__main__":
    main()
