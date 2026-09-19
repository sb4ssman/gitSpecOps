"""The desktop recipe must point at real app assets and dynamic runtime modules."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "git-sync-suggester" / "packaging" / "GitSpecOpsSync.spec"


def test_spec_uses_the_sync_suggester_root_not_its_packaging_folder():
    text = SPEC.read_text(encoding="utf-8")
    ast.parse(text)
    assert 'packaging_dir = Path(SPECPATH).resolve()' in text
    assert 'root = packaging_dir.parent' in text
    assert 'project_root = root.parent' in text
    assert 'str(root / "app" / "fleet_desktop.py")' in text
    assert 'str(root / "ui" / name)' in text
    assert 'str(root / name) for name in ("core", "fleet", "app")' in text
    assert 'pathex=[str(project_root), str(root), *code_dirs]' in text
    assert 'str(tool)' not in text


def test_dynamic_recovery_and_live_modules_are_packaged():
    text = SPEC.read_text(encoding="utf-8")
    for name in ("fleet_actions", "recovery_runtime", "capture", "snapshot_store",
                 "retirement", "vscode_buffers"):
        assert f'"{name}"' in text, name


def main():
    test_spec_uses_the_sync_suggester_root_not_its_packaging_folder()
    test_dynamic_recovery_and_live_modules_are_packaged()
    print("ALL-PACKAGING-SPEC-TESTS-PASS")


if __name__ == "__main__":
    main()
