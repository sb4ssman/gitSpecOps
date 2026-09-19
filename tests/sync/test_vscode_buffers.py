"""VS Code buffer inspection is explicit, bounded, root-confined and content-free in output."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup("sync")
from vscode_buffers import inspect


def test_inspect_reports_only_different_buffers_under_selected_roots():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        library, backups, outside = root / "library", root / "Backups", root / "outside"
        library.mkdir(); backups.mkdir(); outside.mkdir()
        saved = library / "file.txt"; saved.write_text("saved\n")
        other = outside / "other.txt"; other.write_text("saved\n")
        marker = b"BUFFER_PRIVATE_MARKER\n"
        (backups / "one").write_bytes((saved.as_uri() + " backup\n").encode() + marker)
        (backups / "two").write_bytes((other.as_uri() + " backup\n").encode() + marker)
        rows = inspect([library], backups, now=100)
        assert rows and rows[0]["path"] == "file.txt"
        assert marker.decode().strip() not in str(rows), "metadata must not echo editor content"
        assert "outside" not in str(rows)


def main():
    test_inspect_reports_only_different_buffers_under_selected_roots()
    print("ALL-VSCODE-BUFFER-TESTS-PASS")


if __name__ == "__main__":
    main()
