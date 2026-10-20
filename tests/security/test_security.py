"""The Security tools on a disposable repository holding invented personal data.

Pins: history is read whole (file content, file names, commit messages, author/committer
identities); identity values come from seeds, never from the code; the rewrite plan holds the
real values only outside the repository, never rewrites the repository's owner, and never
touches the checkout; verification refuses an unrewritten mirror.

Every value here is invented. Seeds are passed in, so the runner's real identity is never used.
The rewrite itself (`apply`, which runs `git filter-repo`) is exercised only when
GITSPECOPS_RUN_REWRITE_TEST=1 is set -- run it once by hand; it touches only a temporary folder.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup  # noqa: E402

setup()

from Security import _rewrite, rewrite_history  # noqa: E402
from Security._history import scan_history  # noqa: E402
from Security._patterns import find, identity_patterns, mask  # noqa: E402
from Security._repo import patterns_for  # noqa: E402
from Security._report import render  # noqa: E402

FAILS: list[str] = []
SEEDS = {
    "your gh login": ["example-owner"],
    "a tailnet machine name": ["invented-host", "other-invented-box"],
    "a tailnet address": ["100.64.9.9"],
    "your git email": ["someone.real@example-mail.invalid"],
}
TARGET = ("Example Owner", "12345+example-owner@users.noreply.github.com")


def check(label: str, ok: bool, detail: object = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILS.append(f"{label}: {detail}")


def git(repo: Path, *args: str, name="Example Owner", email="someone.real@example-mail.invalid"):
    env = {**os.environ, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
    if done.returncode:
        raise RuntimeError(f"git {args}: {done.stderr}")
    return done.stdout


def commit(repo: Path, message: str, **who) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message, **who)


# --- patterns: identity values are seeds, whole-value only, owner excused only where public ---
patterns = identity_patterns(SEEDS, public_repositories=("proj",))
check("a seeded machine name is found",
      [f.value for f in find("ran on invented-host today", patterns)] == ["invented-host"])
check("a longer word containing it is not",
      not find("invented-hostname-x", {"m": patterns["a tailnet machine name"]}))
check("punctuation does not shield a value (runs/__name.txt, x-name)",
      len(find("runs/__invented-host.txt and x-invented-host", patterns)) == 2)
check("the owner of a public repository is excused there",
      not find("https://example.test/example-owner/proj.git", patterns))
check("the owner beside any other repository is not",
      bool(find("example-owner/private-state", patterns)))
check("masking keeps a value recognizable but unreadable",
      mask("someone.real@example-mail.invalid") == "s***@e***.invalid"
      and "invented" not in mask("other-invented-box"))

with tempfile.TemporaryDirectory(prefix="security-") as temp:
    tmp = Path(temp)
    repo = tmp / "proj"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", "https://example.test/example-owner/proj.git")
    (repo / "README.md").write_text("# proj\nclone https://example.test/example-owner/proj\n")
    commit(repo, "start")
    notes = repo / "notes.md"
    notes.write_text("peer invented-host at 100.64.9.9; also 100.64.9.90 is not it\n")
    (repo / "invented-host.log").write_text("x\n")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "tool.cpython-314.pyc").write_bytes(
        b"\x00\x0d\r\nC:\\Users\\inventedperson\\proj\\tool.py\x00")
    commit(repo, "notes from other-invented-box", name="HOSTBOX\\example-owner")
    (repo / "contrib.md").write_text("thanks\n")
    commit(repo, "a collaborator's commit", name="Collaborator",
           email="collab@example-mail.invalid")
    notes.write_text("peer machine-a at <tailnet-ip>\n")
    (repo / "invented-host.log").unlink()
    commit(repo, "sanitize", email=TARGET[1], name=TARGET[0])
    before_head = git(repo, "rev-parse", "HEAD")
    before_status = git(repo, "status", "--porcelain")

    report = scan_history(repo, ["--all"], patterns_for(repo, SEEDS))
    found = {(e.kind, e.value): e for e in report.exposures.values()}
    check("history finds a value no current file holds",
          ("a tailnet address", "100.64.9.9") in found
          and not found[("a tailnet address", "100.64.9.9")].current, sorted(found))
    check("a longer number containing the address is not taken for it",
          all(e.value != "100.64.9.90" for e in report.exposures.values()))
    check("a value in a file *name* is found",
          any(e.in_paths for e in report.exposures.values() if e.value == "invented-host"))
    check("a value in a commit message is found",
          any(e.commits for e in report.exposures.values() if e.value == "other-invented-box"))
    people = {p.email: p for p in report.personal_identities()}
    check("a real email address on commits is found",
          "someone.real@example-mail.invalid" in people, sorted(people))
    check("a HOST\\user author name is found",
          any("machine name" in p.concern for p in report.personal_identities()))
    check("a noreply identity is not personal data", TARGET[1] not in people)
    check("the repository's owner is not reported as a leak",
          all(e.value != "example-owner" for e in report.exposures.values()))
    text, count = render(report)
    check("the report masks values by default",
          "someone.real" not in text and "100.64.9.9" not in text and count > 0, text)

    # --- the plan: private, outside the repository, owner untouched, checkout untouched --------
    try:
        _rewrite.plan(repo, repo / "plan", seeds=SEEDS, target=TARGET)
        check("a plan folder inside the repository is refused", False)
    except ValueError:
        check("a plan folder inside the repository is refused", True)

    plan_dir = tmp / "private-plan"
    decided = _rewrite.plan(repo, plan_dir, seeds=SEEDS, target=TARGET,
                                   extra={"secret-org-name": "example-org"})
    replacements = (plan_dir / "replacements.txt").read_text(encoding="utf-8")
    mailmap = (plan_dir / "mailmap.txt").read_text(encoding="utf-8")
    check("every found value has a rule; machine names get numbered placeholders",
          decided["replacements"]["invented-host"]["with"] == "machine-a"
          and decided["replacements"]["other-invented-box"]["with"] == "machine-b"
          and decided["replacements"]["100.64.9.9"]["with"] == "<tailnet-ip>", decided)
    check("hand-added values are carried", "secret-org-name" in decided["replacements"])
    # git filter-repo has no comment syntax: every line is a rule, and a line without `==>`
    # replaces that literal text with ***REMOVED*** everywhere. A '#' header once rewrote the
    # code that wrote it; verification caught it before any push.
    rule_lines = [line for line in replacements.splitlines() if line.strip()]
    check("the rules file holds rules only -- no comment, no line without ==>",
          rule_lines and all(line.startswith("regex:") and "==>" in line for line in rule_lines),
          replacements)
    check("the owner is never rewritten", "example-owner" not in decided["replacements"])
    check("rules are word-bounded regular expressions",
          "regex:(?i:(?<![A-Za-z0-9])100\\.64\\.9\\.9(?![A-Za-z0-9]))==><tailnet-ip>"
          in replacements,
          replacements)
    check("every identity of yours maps to the public one",
          f"{TARGET[0]} <{TARGET[1]}> Example Owner <someone.real@example-mail.invalid>" in mailmap
          and "HOSTBOX\\example-owner" in mailmap, mailmap)
    check("a collaborator's identity is never re-attributed to you",
          "collab@example-mail.invalid" not in mailmap
          and any(e["email"] == "collab@example-mail.invalid" for e in decided["others"]),
          decided["others"])
    check("generated bytecode is removed from history, not edited",
          "*.pyc" in decided["remove_paths"] and "__pycache__/*" in decided["remove_paths"],
          decided["remove_paths"])
    check("binary content is reported as only partly inspectable", decided["binary_paths"] >= 1)
    check("each ref records whether its tip holds a planned value",
          decided["refs"]["refs/heads/main"].get("clean_tip") is False,
          decided["refs"])  # the tip still holds the planted .pyc with a user path
    check("the mirror is a bare clone of branches and tags",
          (plan_dir / "mirror.git" / "HEAD").is_file()
          and "refs/heads/main" in decided["refs"]
          and not any(ref.startswith("refs/remotes/") for ref in decided["refs"]))
    check("planning changed nothing in the checkout",
          git(repo, "rev-parse", "HEAD") == before_head
          and git(repo, "status", "--porcelain") == before_status)
    check("the repository holds none of the plan", not (repo / "plan").exists()
          and "invented-host" not in git(repo, "status", "--porcelain", "--ignored"))

    # --- verification refuses an unrewritten mirror -----------------------------------------
    clean, lines = _rewrite.verify(plan_dir)
    check("an unrewritten mirror fails verification, naming what remains",
          not clean and any("still present" in line for line in lines)
          and any("still published" in line for line in lines), lines)
    # A changed tip is named, file by file, not just reported as "changed".
    expected_path = plan_dir / "expected.json"
    saved = expected_path.read_text(encoding="utf-8")
    tampered = json.loads(saved)
    main_ref = tampered["refs"]["refs/heads/main"]
    main_ref.update(tree="0" * 40, clean_tip=True)
    main_ref["files"]["README.md"] = "0" * 40
    tampered["remove_paths"] = []
    expected_path.write_text(json.dumps(tampered), encoding="utf-8")
    _clean, named = _rewrite.verify(plan_dir)
    expected_path.write_text(saved, encoding="utf-8")
    check("a changed tip names the files that changed",
          any("current files changed" in line and "README.md" in line for line in named), named)
    out = io.StringIO()
    with redirect_stdout(out):
        code = rewrite_history.main(["verify", str(plan_dir)])
    check("the verify command exits non-zero and prints no push steps", code == 1
          and "push --force" not in out.getvalue())

    # --- the rewrite itself, only when asked for -----------------------------------------------
    if os.environ.get("GITSPECOPS_RUN_REWRITE_TEST") == "1" and shutil.which("git-filter-repo"):
        out = io.StringIO()
        with redirect_stdout(out):
            code = rewrite_history.main(["apply", str(plan_dir), "--yes"])
        check("apply rewrites the mirror and verifies clean", code == 0, out.getvalue())
        check("then prints the push steps", "push --force" in out.getvalue())
        mirror = plan_dir / "mirror.git"
        old_note = subprocess.run(["git", "-C", str(mirror), "log", "-p", "--all"],
                                  capture_output=True, text=True).stdout
        check("old file versions now hold placeholders",
              "<tailnet-ip>" in old_note and "100.64.9.9;" not in old_note)
        check("the checkout is still untouched", git(repo, "rev-parse", "HEAD") == before_head)
    else:
        print("skip  the rewrite itself (set GITSPECOPS_RUN_REWRITE_TEST=1 with git-filter-repo "
              "installed to run it; it touches only a temporary folder)")

# --- where output goes: inside gitSpecOps, but only somewhere git will never publish ---------
from Security._repo import is_ignored, output_dir  # noqa: E402

where = output_dir(ROOT / "some-scanned-repo")
check("reports land in this checkout's git-ignored output folder",
      ROOT / ".agents" / "output" in where.parents and is_ignored(ROOT, where / "report.txt"),
      where)
check("a tracked path is not mistaken for an ignored one", not is_ignored(ROOT, ROOT / "README.md"))

# --- gitleaks: optional, summarized, never required -------------------------------------------
from Security import scan_secrets  # noqa: E402

lines = scan_secrets.summarize([
    {"RuleID": "github-pat", "Commit": "a" * 40, "File": "notes.md", "Secret": "REDACTED"},
    {"RuleID": "github-pat", "Commit": "b" * 40, "File": "notes.md", "Secret": "REDACTED"},
    {"RuleID": "aws-access-token", "Commit": "b" * 40, "File": "deploy.sh", "Secret": "REDACTED"}])
check("a gitleaks summary counts rules, commits and files",
      "3 candidate secret(s) in 2 commit(s), 2 file(s)" in lines[0]
      and any("github-pat: 2" in line for line in lines), lines)
check("an empty gitleaks report reads as nothing found",
      scan_secrets.summarize([]) == ["gitleaks found nothing."])
original_find = scan_secrets.find_gitleaks
scan_secrets.find_gitleaks = lambda: None
try:
    err = io.StringIO()
    from contextlib import redirect_stderr  # noqa: E402
    with redirect_stderr(err):
        code = scan_secrets.main([str(ROOT)])
    check("without gitleaks: exit 2 and say how to install it, nothing else",
          code == 2 and "winget install" in err.getvalue())
finally:
    scan_secrets.find_gitleaks = original_find

# The commands are importable and answer --help by path from anywhere.
for name in ("scan_tree.py", "scan_history.py", "scan_secrets.py", "rewrite_history.py",
             "scan_folder.py"):
    done = subprocess.run([sys.executable, str(ROOT / "Security" / name), "--help"],
                          capture_output=True, text=True, cwd=tempfile.gettempdir(), timeout=60)
    check(f"Security/{name} --help works from another folder", done.returncode == 0, done.stderr)

# --- second opinions: checksums, low-variety hex, a key header alone, fixture credentials -------
from Security._patterns import SECRETS  # noqa: E402

random_hex = "0123456789abcdef" * 4
ASSIGNED = "pass" + "word="   # split, so this file is not itself a finding
check("a checksum after sha256: / \"sha256\": is not a secret",
      not find(f'hash = "sha256:{random_hex}"', SECRETS)
      and not find(f'"sha256": "{random_hex}"', SECRETS))
check("a bare 64-hex value still is", bool(find(f"fleet = {random_hex}", SECRETS)))
check("a low-variety run (bitmap rows) is not", not find("ab" * 32, SECRETS))
check("a private key header with no key after it is not a secret",
      not find('"-----BEGIN PRIVATE KEY-----".encode()', SECRETS))
check("a private key block with a body is",
      bool(find("-----BEGIN PRIVATE KEY-----\n" + "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC" * 2,
                SECRETS)))
check("a credential that says it is a sample is not; a real-looking one is",
      not find(ASSIGNED + '"sample-value"', SECRETS)
      and bool(find(ASSIGNED + '"h7Qz9pLm2xWv"', SECRETS)))
check("Homebrew's Linux prefix is not a home folder",
      not find("/home/linuxbrew/.linuxbrew", patterns_for(ROOT, {})))

# --- what is inside a binary file: archive members, image metadata ----------------------------
import io as _io  # noqa: E402
import struct  # noqa: E402
import tarfile  # noqa: E402
import zipfile  # noqa: E402
import zlib  # noqa: E402

from Security import _contents  # noqa: E402


def zipped(members: dict) -> bytes:
    buffer = _io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def tarred(members: dict, mode="w:gz") -> bytes:
    buffer = _io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, _io.BytesIO(data))
    return buffer.getvalue()


def png_with(chunks: list[tuple[bytes, bytes]]) -> bytes:
    out = b"\x89PNG\r\n\x1a\n"
    for kind, body in [(b"IHDR", b"\0" * 13), *chunks, (b"IEND", b"")]:
        out += struct.pack(">I4s", len(body), kind) + body + b"\0\0\0\0"
    return out


def exif(entries: list[tuple[int, int, int, bytes]], gps: bool) -> bytes:
    """A little-endian TIFF: IFD0 with `entries` (+ a GPS pointer), and a GPS IFD."""
    count = len(entries) + (1 if gps else 0)
    ifd0_size = 2 + 12 * count + 4
    data_at = 8 + ifd0_size
    gps_at = data_at + sum(len(v) for *_, v in entries if len(v) > 4)
    body, extra = struct.pack("<H", count), b""
    for tag, kind, n, value in entries:
        if len(value) > 4:
            body += struct.pack("<HHII", tag, kind, n, data_at + len(extra))
            extra += value
        else:
            body += struct.pack("<HHI", tag, kind, n) + value.ljust(4, b"\0")
    if gps:
        body += struct.pack("<HHII", 0x8825, 4, 1, gps_at)
    body += b"\0\0\0\0"
    gps_ifd = struct.pack("<H", 1) + struct.pack("<HHII", 2, 5, 3, 0) + b"\0\0\0\0"
    return b"II*\0" + struct.pack("<I", 8) + body + extra + (gps_ifd if gps else b"")


def jpeg_with(tiff: bytes) -> bytes:
    app1 = b"Exif\0\0" + tiff
    return b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9"


opened = _contents.open_archive("bundle.zip", zipped({"notes.txt": b"ran on invented-host"}))
check("a zip's members are read", opened.members == [("notes.txt", b"ran on invented-host")])
nested = _contents.open_archive("outer.tar.gz", tarred(
    {"inner.zip": zipped({"deep.txt": b"invented-host"})}))
check("an archive inside an archive is opened too",
      ("inner.zip!deep.txt", b"invented-host") in nested.members, nested.members)
check("a 7z archive is reported, not silently skipped",
      _contents.open_archive("x.7z", b"7z\xbc\xaf").skipped)
check("a damaged archive is reported, not raised",
      _contents.open_archive("x.zip", b"PK not really").skipped)
saved_limit = _contents.MEMBER_LIMIT_BYTES
_contents.MEMBER_LIMIT_BYTES = 10
try:
    big = _contents.open_archive("big.zip", zipped({"huge.txt": b"x" * 100}))
    check("a member over the size limit is reported, not read",
          not big.members and big.skipped, big.skipped)
finally:
    _contents.MEMBER_LIMIT_BYTES = saved_limit
author = "invented-host".encode("utf-16-le") + b"\0\0"
metadata = _contents.image_metadata(jpeg_with(exif(
    [(0x013B, 2, 14, b"Example Owner\0"), (0x9C9D, 1, len(author), author)], gps=True)))
check("JPEG EXIF: text fields, Windows' UTF-16 author tag and the GPS position are read",
      metadata and metadata.gps and "Example Owner" in metadata.texts
      and "invented-host" in metadata.texts, metadata)
check("an image without a GPS position says so",
      _contents.image_metadata(jpeg_with(exif([(0x013B, 2, 5, b"anon\0")], gps=False))).gps
      is False)
png = _contents.image_metadata(png_with([
    (b"tEXt", b"Author\0invented-host"),
    (b"zTXt", b"Comment\0\0" + zlib.compress(b"shot on other-invented-box"))]))
check("PNG text chunks, compressed ones too, are read",
      png and any("invented-host" in t for t in png.texts)
      and any("other-invented-box" in t for t in png.texts), png)
check("bytes that are no image are not mistaken for one", _contents.image_metadata(b"GIF89a")
      is None)

# --- history: inside archives and photos; what text replacement cannot reach -------------------
with tempfile.TemporaryDirectory(prefix="security-binary-") as temp:
    repo = Path(temp) / "proj"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", "https://example.test/example-owner/proj.git")
    (repo / "logs.zip").write_bytes(zipped({"run.log": b"peer invented-host"}))
    (repo / "photo.jpg").write_bytes(jpeg_with(exif([], gps=True)))
    (repo / "README.md").write_text("# proj\n")
    commit(repo, "start", email=TARGET[1], name=TARGET[0])
    report = scan_history(repo, ["--all"], patterns_for(repo, SEEDS))
    inside = [e for e in report.exposures.values() if e.value == "invented-host"]
    check("a value inside an archive is found and located as archive!member",
          inside and "logs.zip!run.log" in inside[0].paths, [e.paths for e in inside])
    check("a photo with a GPS position is reported", report.located_images == {"photo.jpg"})
    decided = _rewrite.build_plan(report, target=TARGET, owner="example-owner")
    check("the plan says text replacement cannot reach the archive",
          decided["unreachable"].get("logs.zip") == _rewrite.UNREACHABLE_ARCHIVE,
          decided["unreachable"])
    check("the plan lists the located photo", decided["images_with_location"] == ["photo.jpg"])
    removed = _rewrite.build_plan(report, target=TARGET, owner="example-owner",
                                         remove=["logs.zip"], keep=["photo.jpg"])
    check("--remove-path and --keep settle both",
          not removed["unreachable"] and not removed["images_with_location"]
          and "logs.zip" in removed["remove_paths"], removed)
    text, _count = render(report)
    check("the report shows the photo and the opened archive",
          "photo.jpg" in text and "Opened 1 archive" in text, text)

# --- your own old address, under another name, is yours ---------------------------------------
from Security._history import HistoryReport, Identity  # noqa: E402

old = HistoryReport(refs=[])
for name in ("example-owner", "Old Account Name"):
    old.identities[(name, "someone.old@example-mail.invalid")] = Identity(
        name, "someone.old@example-mail.invalid", commits=3)
widened = _rewrite.widen_seeds(old, {"your gh login": ["example-owner"]})
check("an address your own name used becomes a search pattern",
      widened and "someone.old@example-mail.invalid" in widened["your git email"], widened)
both = _rewrite.build_plan(old, target=TARGET, owner=None,
                                  my_names=["example-owner"])
check("and every identity using it is re-attributed, whatever its name",
      {entry["name"] for entry in both["mailmap"]} == {"example-owner", "Old Account Name"}
      and not both["others"], both)
old.identities[("Other Account", "999+other@users.noreply.github.com")] = Identity(
    "Other Account", "999+other@users.noreply.github.com", commits=2)
claimed = _rewrite.build_plan(old, target=TARGET, owner=None, my_names=["example-owner"],
                              claim=["999+other@users.noreply.github.com"])
check("--mine claims another account's noreply identity too (not personal data, still a name)",
      "Other Account" in {entry["name"] for entry in claimed["mailmap"]}
      and "Other Account" not in {entry["name"] for entry in both["mailmap"]}, claimed)

# --- the rules file: backslashes in a placeholder, file names ---------------------------------
import re as _re  # noqa: E402

line = _rewrite._replacements_text({"replacements": {
    "C:\\Users\\inventedperson": {"with": "C:\\Users\\<you>"}}}).strip()
pattern, _, template = line[len("regex:"):].partition("==>")
check("a placeholder with backslashes is a valid replacement template (filter-repo crashed)",
      _re.compile(pattern).sub(template, "at C:\\Users\\inventedperson\\x")
      == "at C:\\Users\\<you>\\x", line)
with tempfile.TemporaryDirectory(prefix="security-rules-") as temp:
    rules = Path(temp) / "replacements.txt"
    rules.write_text(_rewrite._replacements_text({"replacements": {
        "invented-host": {"with": "machine-a"}}}), encoding="utf-8")
    scope: dict = {}
    body = _rewrite._filename_callback(rules)
    exec("def callback(filename):\n" + "".join(f"    {row}\n" for row in body.splitlines()),
         scope)
    check("file names are rewritten by the same rules (filter-repo's --replace-text does not)",
          scope["callback"](b"logs/invented-host.log") == b"logs/machine-a.log"
          and scope["callback"](None) is None)

# --- relink: commit ids quoted in files, from the commit map ----------------------------------
olds = {"a1b2c3d4" + "0" * 32: "f9e8d7c6" + "1" * 32, "a1b2ffff" + "0" * 32: "0badc0de" + "2" * 32}
found = _rewrite.references("see a1b2c3d and a1b2 and a1b2c3d4000 and deadbee", olds)
check("a quoted id naming exactly one old commit is mapped, at its own length",
      [(old, new) for _offset, old, new in found] == [("a1b2c3d", "f9e8d7c"),
                                                      ("a1b2c3d4000", "f9e8d7c6111")], found)
with tempfile.TemporaryDirectory(prefix="security-relink-") as temp:
    tmp = Path(temp)
    checkout = tmp / "proj"
    checkout.mkdir()
    git(checkout, "init", "-q", "-b", "main")
    (checkout / "LOG.md").write_text("fixed in a1b2c3d\n")
    commit(checkout, "log", email=TARGET[1], name=TARGET[0])
    plan_dir = tmp / "plan"
    (plan_dir / "mirror.git" / "filter-repo").mkdir(parents=True)
    (plan_dir / "mirror.git" / "filter-repo" / "commit-map").write_text(
        "old                                      new\n"
        + "".join(f"{old} {new}\n" for old, new in olds.items()), encoding="ascii")
    lines, total = _rewrite.relink(plan_dir, checkout)
    check("relink lists the quoted ids and changes nothing without --write",
          total == 1 and "LOG.md:1" in lines[0]
          and (checkout / "LOG.md").read_text() == "fixed in a1b2c3d\n", lines)
    _rewrite.relink([plan_dir], checkout, write=True)
    check("with write, the file holds the new id and nothing is committed",
          (checkout / "LOG.md").read_text() == "fixed in f9e8d7c\n"
          and git(checkout, "status", "--porcelain").strip() == "M LOG.md")
    head = git(checkout, "rev-parse", "HEAD").strip()
    (plan_dir / "mirror.git" / "filter-repo" / "commit-map").write_text(
        f"old new\n{head} {'3' * 40}\n", encoding="ascii")
    try:
        _rewrite.relink(plan_dir, checkout)
        check("relink refuses a checkout still on the old history", False)
    except ValueError:
        check("relink refuses a checkout still on the old history", True)

# --- follow: a clone made before the rewrite --------------------------------------------------
from contextlib import redirect_stderr  # noqa: E402

from Basic._confirm import use_scripted_answers  # noqa: E402
from Basic._facts import shares_history  # noqa: E402


def rewrite_bare(bare: Path, work: Path) -> None:
    """What filter-repo does, by hand: every commit again, same trees and times, new identity."""
    git(work, "fetch", "-q", "origin")
    mapping, parent = {}, None
    for sha in git(work, "rev-list", "--reverse", "origin/main").split():
        fields = git(work, "log", "-1", "--format=%T%x00%aI%x00%cI%x00%B", sha).split("\0")
        env = {**os.environ, "GIT_AUTHOR_NAME": TARGET[0], "GIT_AUTHOR_EMAIL": TARGET[1],
               "GIT_COMMITTER_NAME": TARGET[0], "GIT_COMMITTER_EMAIL": TARGET[1],
               "GIT_AUTHOR_DATE": fields[1], "GIT_COMMITTER_DATE": fields[2]}
        args = ["git", "-C", str(work), "commit-tree", fields[0], "-m", fields[3].strip()]
        if parent:
            args[5:5] = ["-p", parent]
        parent = subprocess.run(args, capture_output=True, text=True, env=env,
                                check=True).stdout.strip()
        mapping[sha] = parent
    git(work, "push", "-q", "--force", "origin", f"{parent}:refs/heads/main")
    return mapping


# Every commit in one second: matching rewritten commits by their times once let `follow` take
# a never-pushed commit for a published one (caught by the full suite, which runs fast).
os.environ["GIT_AUTHOR_DATE"] = os.environ["GIT_COMMITTER_DATE"] = "2026-01-01T00:00:00+00:00"
with tempfile.TemporaryDirectory(prefix="security-follow-") as temp:
    tmp = Path(temp)
    bare = tmp / "remote.git"
    git(tmp, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp / "seed"
    git(tmp, "clone", "-q", str(bare), str(seed))
    for step in range(3):
        (seed / "f.txt").write_text(f"step {step}\n")
        commit(seed, f"step {step}")
    git(seed, "push", "-q", "origin", "main")
    clean = tmp / "clean"
    ahead = tmp / "ahead"
    dirty = tmp / "dirty"
    unlogged = tmp / "unlogged"
    for clone in (clean, ahead, dirty, unlogged):
        git(tmp, "clone", "-q", str(bare), str(clone))
    (ahead / "mine.txt").write_text("only here\n")
    commit(ahead, "work made only in this clone")
    git(clean, "branch", "-q", "old-side")
    rewrite_bare(bare, seed)
    for clone in (clean, ahead, dirty, unlogged):
        git(clone, "fetch", "-q", "origin")
    git(unlogged, "reflog", "expire", "--expire=now", "--all")
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        unproven = _rewrite.follow(unlogged, fetch=False, assume_yes=True)
    check("with no record of what the remote held, follow refuses rather than guess",
          unproven == 1 and shares_history(unlogged) is False)
    check("a clone made before the rewrite shares no history with its upstream",
          shares_history(clean) is False)
    (dirty / "f.txt").write_text("edited\n")
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        dirty_code = _rewrite.follow(dirty, fetch=False, assume_yes=True)
        ahead_code = _rewrite.follow(ahead, fetch=False, assume_yes=True)
    check("follow refuses a changed tracked file", dirty_code == 1
          and (dirty / "f.txt").read_text() == "edited\n")
    check("follow refuses when a commit exists only in this clone",
          ahead_code == 1 and (ahead / "mine.txt").is_file()
          and shares_history(ahead) is False)
    use_scripted_answers(["n"])
    with redirect_stdout(io.StringIO()):
        declined = _rewrite.follow(clean, fetch=False)
    check("declining moves nothing", declined == 1 and shares_history(clean) is False)
    out = io.StringIO()
    with redirect_stdout(out):
        moved = _rewrite.follow(clean, fetch=False, assume_yes=True)
    check("follow moves a clean clone onto the rewritten history",
          moved == 0 and shares_history(clean) is True
          and git(clean, "rev-parse", "HEAD") == git(clean, "rev-parse", "origin/main"),
          out.getvalue())
    check("and names a local branch still in the old history", "old-side" in out.getvalue(),
          out.getvalue())
    with redirect_stdout(io.StringIO()):
        again = _rewrite.follow(clean, fetch=False, assume_yes=True)
    check("following again is a no-op", again == 0)

    # The observer says what happened instead of calling it divergence.
    setup("sync")
    from observer import observe_paths  # noqa: E402

    observation = observe_paths([ahead])
    check("Sync Suggester names a rewritten upstream, without the path in the category",
          any(issue.startswith("upstream history was rewritten; move this clone with "
                               "Security/rewrite_history.py follow: ")
              for issue in observation.issues), observation.issues)

# --- finish: after the forced push, one command moves the checkout and relinks it -------------
with tempfile.TemporaryDirectory(prefix="security-finish-") as temp:
    tmp = Path(temp)
    bare = tmp / "remote.git"
    git(tmp, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp / "seed"
    git(tmp, "clone", "-q", str(bare), str(seed))
    (seed / "f.txt").write_text("one\n")
    commit(seed, "one")
    first = git(seed, "rev-parse", "HEAD").strip()
    (seed / "LOG.md").write_text(f"see {first[:7]}\n")
    commit(seed, "two")
    git(seed, "push", "-q", "origin", "main")
    work = tmp / "work"
    git(tmp, "clone", "-q", str(bare), str(work))
    mapping = rewrite_bare(bare, seed)
    plan_dir = tmp / "plan"
    (plan_dir / "mirror.git" / "filter-repo").mkdir(parents=True)
    (plan_dir / "mirror.git" / "filter-repo" / "commit-map").write_text(
        "old new\n" + "".join(f"{old} {new}\n" for old, new in mapping.items()), encoding="ascii")
    (plan_dir / "expected.json").write_text(json.dumps({"repository": str(work), "refs": {}}),
                                            encoding="utf-8")
    (work / "scratch.txt").write_text("mine, untracked\n")
    with redirect_stdout(io.StringIO()) as out:
        finished = _rewrite.finish([plan_dir], assume_yes=True)
    check("finish moves the checkout, relinks its quoted ids, commits exactly those and pushes",
          finished == 0 and shares_history(work) is True
          and (work / "LOG.md").read_text() == f"see {mapping[first][:7]}\n"
          and git(work, "status", "--porcelain").strip() == "?? scratch.txt"
          and git(work, "log", "-1", "--format=%s").strip() == _rewrite.RELINK_MESSAGE
          and git(work, "rev-parse", "HEAD") == git(bare, "rev-parse", "main"), out.getvalue())

    # Another machine: one line moves every stale checkout under a folder, refusing the unsafe.
    with redirect_stdout(io.StringIO()):
        nothing = _rewrite.follow_many([tmp], match=["no-such-remote"], assume_yes=True)
    check("a --match that names nothing changes nothing", nothing == 2)
    with redirect_stdout(io.StringIO()) as out:
        swept = _rewrite.follow_many([tmp], match=["remote.git"], assume_yes=True)
    check("one sweep moves every stale clone under a folder and leaves current ones alone",
          shares_history(seed) is True and shares_history(work) is True
          and git(seed, "rev-parse", "HEAD") == git(bare, "rev-parse", "main")
          and swept == 0 and "Moved 1; refused 0" in out.getvalue(), out.getvalue())
    steps = "\n".join(_rewrite.push_steps([plan_dir, plan_dir]))
    check("after apply: one push line per plan, then a single finish line",
          steps.count("push --force") == 2 and steps.count("rewrite_history.py finish") == 1,
          steps)

os.environ.pop("GIT_AUTHOR_DATE")
os.environ.pop("GIT_COMMITTER_DATE")

if FAILS:
    print(f"\n{len(FAILS)} FAILED")
    for failure in FAILS:
        print(" -", failure)
    raise SystemExit(1)
print("\nALL-SECURITY-TESTS-PASS")
