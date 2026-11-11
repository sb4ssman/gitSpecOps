"""The desktop recipe must point at the real entry, the real skin files and the lazy modules."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "_build" / "GitSpecOpsSync.spec"


def test_spec_builds_the_app_entry_from_the_repository_root():
    text = SPEC.read_text(encoding="utf-8")
    ast.parse(text)
    assert 'build_dir = Path(SPECPATH).resolve()' in text
    assert 'project_root = build_dir.parent' in text
    assert 'str(project_root / "App" / "desktop.py")' in text
    assert 'pathex=[str(project_root)]' in text
    assert (ROOT / "App" / "desktop.py").is_file()


def test_every_skin_file_the_server_serves_is_packaged():
    sys.path.insert(0, str(ROOT))
    from App._web._assets import ASSETS

    text = SPEC.read_text(encoding="utf-8")
    for name, _mime in ASSETS.values():
        assert f'"{name}"' in text, name


def test_lazy_modules_are_named_and_exist():
    text = SPEC.read_text(encoding="utf-8")
    for module in ("App._tray.qt", "Elaborate._recovery.runtime", "Special._sync.actions",
                   "Elaborate._recovery.capture", "Elaborate._recovery.snapshot_store",
                   "Elaborate._recovery.retirement", "Special._sync.vscode_buffers"):
        assert f'"{module}"' in text, module
        assert (ROOT / (module.replace(".", "/") + ".py")).is_file(), module


def main():
    test_spec_builds_the_app_entry_from_the_repository_root()
    test_every_skin_file_the_server_serves_is_packaged()
    test_lazy_modules_are_named_and_exist()
    print("ALL-PACKAGING-SPEC-TESTS-PASS")


if __name__ == "__main__":
    main()
