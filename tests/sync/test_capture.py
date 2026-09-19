"""Recovery capture: faithful, refusable, and read-only against real repositories."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup

setup("sync")
import capture
from capture import CapturePolicy, CaptureRefused
from secret_scan import findings_in_text, scan_bundle

GIT_ENV = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid",
           "-c", "commit.gpgsign=false"]


def git(repository, *args, check=True):
    result = subprocess.run(["git", *GIT_ENV, *args], cwd=repository,
                            capture_output=True, text=True)
    if check and result.returncode:
        raise AssertionError(f"git {args} failed: {result.stderr}")
    return result


def new_repository(root: Path) -> Path:
    repository = root / "work"
    repository.mkdir()
    git(repository, "init", "-q", "-b", "main")
    (repository / "tracked.txt").write_text("original\n")
    git(repository, "add", "tracked.txt")
    git(repository, "commit", "-qm", "base")
    return repository


def refused(call, expect=""):
    try:
        call()
    except CaptureRefused as exc:
        assert expect in str(exc), f"expected {expect!r} in {exc}"
        return str(exc)
    raise AssertionError("expected a refusal")


def test_staged_and_unstaged_stay_separate():
    """The reason a lone `git diff HEAD` is not enough: it loses the index."""
    with tempfile.TemporaryDirectory() as temp:
        repository = new_repository(Path(temp))
        (repository / "tracked.txt").write_text("staged version\n")
        git(repository, "add", "tracked.txt")
        (repository / "tracked.txt").write_text("worktree version\n")

        bundle = capture.capture(repository, "r1", "machine-a")
        # HEAD -> index carries the staged text as an addition...
        assert "+staged version" in bundle.staged_patch
        assert "-original" in bundle.staged_patch
        # ...and index -> worktree is relative to the index, so it *removes* that same staged
        # text. Neither patch alone describes the repository; that is why both are captured.
        assert "-staged version" in bundle.unstaged_patch
        assert "+worktree version" in bundle.unstaged_patch
        assert "original" not in bundle.unstaged_patch, "the unstaged patch is not against HEAD"
        assert bundle.base_commit and bundle.branch == "main"
        assert not bundle.is_empty

        body = bundle.to_dict()
        assert body["format"] == capture.FORMAT and body["format_version"] == 1
        assert body["checksum"] == capture.checksum_of(body), "checksum must verify"
        tampered = {**body, "staged_patch": body["staged_patch"] + "x"}
        assert capture.checksum_of(tampered) != body["checksum"], "tampering must be detectable"


def test_capture_never_mutates_the_repository():
    with tempfile.TemporaryDirectory() as temp:
        repository = new_repository(Path(temp))
        (repository / "tracked.txt").write_text("dirty\n")
        git(repository, "add", "tracked.txt")
        (repository / "loose.txt").write_text("untracked\n")
        before = git(repository, "status", "--porcelain=v1", "-uall").stdout
        head = git(repository, "rev-parse", "HEAD").stdout

        capture.capture(repository, "r1", "machine-a", untracked=["loose.txt"])

        assert git(repository, "status", "--porcelain=v1", "-uall").stdout == before
        assert git(repository, "rev-parse", "HEAD").stdout == head
        assert git(repository, "stash", "list").stdout == "", "capture must never stash"


def test_untracked_selection_is_explicit_and_screened():
    with tempfile.TemporaryDirectory() as temp:
        repository = new_repository(Path(temp))
        (repository / "wanted.txt").write_text("keep me\n")
        (repository / "ignored.txt").write_text("noise\n")
        (repository / ".gitignore").write_text("ignored.txt\n")

        candidates = capture.untracked_candidates(repository)
        assert "wanted.txt" in candidates
        assert "ignored.txt" not in candidates, "git ignore rules must be respected"

        # Nothing is captured merely by existing; selection is explicit.
        assert capture.capture(repository, "r1", "machine-a").files == []
        bundle = capture.capture(repository, "r1", "machine-a", untracked=["wanted.txt"])
        assert [item["path"] for item in bundle.files] == ["wanted.txt"]
        # Byte-exact, including the platform's line endings as written on disk.
        on_disk = (repository / "wanted.txt").read_bytes()
        assert base64.b64decode(bundle.files[0]["content_base64"]) == on_disk
        assert bundle.files[0]["size"] == len(on_disk)


def test_policy_exclusions_hold_even_when_selected():
    with tempfile.TemporaryDirectory() as temp:
        repository = new_repository(Path(temp))
        (repository / ".env").write_text("TOKEN=abc\n")
        (repository / "server.pem").write_text("material\n")
        bundle = capture.capture(repository, "r1", "machine-a",
                                 untracked=[".env", "server.pem"])
        assert bundle.files == [], "policy exclusions must beat an explicit selection"
        assert len(bundle.notes) == 2 and all("excluded" in note for note in bundle.notes)


def test_a_secret_refuses_the_whole_snapshot():
    with tempfile.TemporaryDirectory() as temp:
        repository = new_repository(Path(temp))
        leaked = "AKIA" + "A" * 16
        (repository / "config.py").write_text(f'AWS_KEY = "{leaked}"\n')
        message = refused(
            lambda: capture.capture(repository, "r1", "machine-a",
                                    untracked=["config.py"], scan=scan_bundle),
            "possible credentials")
        # The refusal is itself a place a secret must not be copied to.
        assert leaked not in message and "AWS access key id" in message
        assert "config.py" in message, "the path and rule are what the user needs"


def test_scanner_rules():
    # Credential-shaped fixtures are assembled at runtime so this public repository's own
    # hygiene gate (tests/repo/test_repo_hygiene.py) never sees a literal that looks real.
    key_header = "-----BEGIN RSA " + "PRIVATE KEY-----"
    assigned = "pass" + "word"
    assert findings_in_text(key_header, "f")
    assert findings_in_text(f'{assigned} = "hunter2horse"', "f")
    assert findings_in_text("ghp_" + "a" * 36, "f")
    # Shape, not vocabulary: placeholders and short values must not cry wolf.
    assert not findings_in_text(f"{assigned} = changeme", "f")
    assert not findings_in_text(f'{assigned} = "${{VAULT_PASSWORD}}"', "f")
    assert not findings_in_text("# set your password in the environment", "f")
    assert not findings_in_text("AKIA-not-a-key", "f")
    assert not findings_in_text("this is ordinary prose about a secret garden", "f")


def test_refusals_that_protect_fidelity():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        repository = new_repository(root)

        # An unborn branch has no base to patch against.
        empty = root / "empty"
        empty.mkdir()
        git(empty, "init", "-q", "-b", "main")
        refused(lambda: capture.capture(empty, "r2", "machine-a"), "no commit yet")

        # A half-finished operation would restore a broken state.
        (repository / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n")
        refused(lambda: capture.capture(repository, "r1", "machine-a"), "merge is in progress")
        (repository / ".git" / "MERGE_HEAD").unlink()

        # Oversized content is refused, never truncated.
        big = repository / "big.bin"
        big.write_bytes(b"x" * (capture.MAX_FILE_BYTES + 1))
        refused(lambda: capture.capture(repository, "r1", "machine-a", untracked=["big.bin"]),
                "per-file limit")
        big.unlink()

        # A tree changing mid-capture must not produce a bundle that never existed on disk.
        writes = {"count": 0}
        real_state = capture.repository_state

        def changing(path):
            writes["count"] += 1
            if writes["count"] == 2:
                (repository / "tracked.txt").write_text(f"moved {writes['count']}\n")
            return real_state(path)

        capture.repository_state = changing
        try:
            refused(lambda: capture.capture(repository, "r1", "machine-a"), "changed while")
        finally:
            capture.repository_state = real_state


def test_bundle_is_json_serialisable_and_names_nothing_extra():
    with tempfile.TemporaryDirectory() as temp:
        repository = new_repository(Path(temp))
        (repository / "tracked.txt").write_text("changed\n")
        body = capture.capture(repository, "opaque-id", "machine-a").to_dict()
        text = json.dumps(body)
        assert "opaque-id" in text
        # The bundle identifies its repository by the opaque id, never by local path or owner.
        assert str(repository) not in text and repository.name not in text


def test_user_diff_config_cannot_change_patch_headers():
    """Preview and restore parse `a/` and `b/` on another machine; local config can't move them."""
    with tempfile.TemporaryDirectory() as temp:
        repository = new_repository(Path(temp))
        git(repository, "config", "diff.mnemonicPrefix", "true")
        git(repository, "config", "diff.noprefix", "true")
        (repository / "tracked.txt").write_text("staged\n")
        git(repository, "add", "tracked.txt")
        (repository / "tracked.txt").write_text("unstaged\n")
        bundle = capture.capture(repository, "r1", "machine-a")
        for patch in (bundle.staged_patch, bundle.unstaged_patch):
            assert "diff --git a/tracked.txt b/tracked.txt" in patch, patch
            assert "--- a/tracked.txt" in patch and "+++ b/tracked.txt" in patch


def test_non_utf8_text_is_refused_not_mangled():
    """Decoding with replacement would store a patch that silently differs from the file."""
    with tempfile.TemporaryDirectory() as temp:
        repository = new_repository(Path(temp))
        (repository / "tracked.txt").write_bytes(b"caf\xe9 written as latin-1\n")
        refused(lambda: capture.capture(repository, "r1", "machine-a"), "not valid UTF-8")


def test_capture_policy_toggles():
    """Defaults protect; each protection can be relaxed locally, and relaxing is recorded."""
    with tempfile.TemporaryDirectory() as temp:
        repository = new_repository(Path(temp))
        credential = "AKIA" + "B" * 16
        (repository / ".gitignore").write_text("*.log\n.env\n")
        (repository / "debug.log").write_text("noise\n")
        (repository / ".env").write_text("CLOUD=" + credential + "\n")
        (repository / "settings.py").write_text("VALUE = '" + credential + "'\n")

        # Defaults: ignored files are not carried, even when explicitly selected.
        default = capture.capture(repository, "r1", "machine-a",
                                  untracked=["debug.log", ".env"])
        assert default.files == []
        assert sum("gitignore" in note for note in default.notes) == 2, default.notes

        # Obey-gitignore off: the ignored log is carried; .env is still held back by name.
        loose = capture.capture(repository, "r1", "machine-a", untracked=["debug.log", ".env"],
                                policy=CapturePolicy(obey_gitignore=False))
        assert [item["path"] for item in loose.files] == ["debug.log"]
        assert any("credential file" in note for note in loose.notes), loose.notes
        assert any("not obeyed" in note for note in loose.notes), "relaxing must be recorded"

        # Allowing .env by path carries it unscreened, while every other file is still screened.
        allow_env = CapturePolicy(obey_gitignore=False, allow_paths=(".env",))
        allowed = capture.capture(repository, "r1", "machine-a", untracked=[".env"],
                                  policy=allow_env)
        assert [item["path"] for item in allowed.files] == [".env"]
        assert any("allowed" in note and ".env" in note for note in allowed.notes)
        refused(lambda: capture.capture(repository, "r1", "machine-a",
                                        untracked=[".env", "settings.py"], policy=allow_env),
                "settings.py")

        # Protection off entirely: carried, and the bundle says nothing was screened.
        bare = capture.capture(repository, "r1", "machine-a", untracked=[".env", "settings.py"],
                               policy=CapturePolicy(obey_gitignore=False,
                                                    secret_protection=False))
        assert {item["path"] for item in bare.files} == {".env", "settings.py"}
        assert any("secret protection is off" in note for note in bare.notes)

        # .git is structural: no policy setting can carry it.
        structural = capture.capture(repository, "r1", "machine-a", untracked=[".git/config"],
                                     policy=CapturePolicy(obey_gitignore=False,
                                                          secret_protection=False))
        assert structural.files == []


def test_screening_reads_only_what_the_snapshot_adds():
    """Rotating a committed secret out must not be refused; adding one must be."""
    credential = "AKIA" + "C" * 16
    with tempfile.TemporaryDirectory() as temp:
        repository = new_repository(Path(temp))
        (repository / "tracked.txt").write_text("VALUE=" + credential + "\n")
        git(repository, "add", "tracked.txt")
        git(repository, "commit", "-qm", "the mistake is already committed")
        (repository / "tracked.txt").write_text("rotated away\n")
        removal = capture.capture(repository, "r1", "machine-a")
        assert "rotated away" in removal.unstaged_patch

        # Re-adding the *same* committed line would be diff context, not an addition, and
        # correctly unflagged: it is already in history. A new credential is an addition.
        fresh = "AKIA" + "D" * 16
        (repository / "tracked.txt").write_text("rotated away\nVALUE=" + fresh + "\n")
        message = refused(lambda: capture.capture(repository, "r1", "machine-a"),
                          "possible credentials")
        assert fresh not in message and "tracked.txt" in message


def main():
    test_capture_policy_toggles()
    test_screening_reads_only_what_the_snapshot_adds()
    test_non_utf8_text_is_refused_not_mangled()
    test_user_diff_config_cannot_change_patch_headers()
    test_staged_and_unstaged_stay_separate()
    test_capture_never_mutates_the_repository()
    test_untracked_selection_is_explicit_and_screened()
    test_policy_exclusions_hold_even_when_selected()
    test_a_secret_refuses_the_whole_snapshot()
    test_scanner_rules()
    test_refusals_that_protect_fidelity()
    test_bundle_is_json_serialisable_and_names_nothing_extra()
    print("ALL-CAPTURE-TESTS-PASS")


if __name__ == "__main__":
    main()
