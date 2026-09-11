"""Version contract: one source of truth, and an update check that cannot mislead or fail.

The update check is the foundation for "am I current?", so its failure behaviour matters more
than its success behaviour: an unreachable network, a missing gh, or a repository with no
releases yet must all report **unknown**, never "up to date". Claiming current without having
checked is the same silence-as-good-news error the fleet freshness rules exist to prevent.

Offline: every check here either works on pure data or stubs the release lookup.
"""
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import ROOT, setup  # noqa: E402

setup("sync")

import shared.version as version  # noqa: E402
from fleet_display import build_display  # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def test_version_is_declared_once():
    """pyproject and the display contract must not be able to drift from shared/version.py."""
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    check(declared["project"]["version"] == version.VERSION,
          f"pyproject {declared['project']['version']} != shared.version {version.VERSION}")
    product = build_display([], "fleet-id")["product"]
    check(product["version"] == version.VERSION,
          f"display contract {product['version']} != shared.version {version.VERSION}")


def test_ordering():
    check(version.is_newer("0.3.0", "0.2.0"), "0.3.0 is newer than 0.2.0")
    check(version.is_newer("0.10.0", "0.9.0"), "numeric compare, not lexicographic")
    check(version.is_newer("v1.0.0", "0.9.9"), "a leading v must be tolerated")
    check(not version.is_newer("0.2.0", "0.2.0"), "equal is not newer")
    check(not version.is_newer("0.1.0", "0.2.0"), "older is not newer")
    check(not version.is_newer("garbage", "0.2.0"), "an unparseable tag must not look newer")


def test_unreachable_check_reports_unknown_not_current():
    original = version.latest_release
    version.latest_release = lambda timeout=15: None
    try:
        status = version.check_for_update()
        check(status["state"] == "unknown", f"expected unknown, got {status['state']}")
        check("up to date" not in status["message"],
              f"must not imply currency when nothing was checked: {status['message']}")
        check(status["current"] == version.VERSION, "current version must still be reported")
    finally:
        version.latest_release = original


def test_outdated_and_current():
    original = version.latest_release
    try:
        version.latest_release = lambda timeout=15: "99.0.0"
        status = version.check_for_update()
        check(status["state"] == "outdated", "a newer release must be reported as outdated")
        check(version.RELEASES_URL in status["url"], "the user needs somewhere to go")

        version.latest_release = lambda timeout=15: version.VERSION
        check(version.check_for_update()["state"] == "current", "same version is current")

        version.latest_release = lambda timeout=15: "0.0.1"
        check(version.check_for_update()["state"] == "current",
              "an older published release must not be offered as an update")
    finally:
        version.latest_release = original


def test_check_never_raises_on_a_broken_lookup():
    original = version.latest_release

    def explode(timeout=15):
        raise RuntimeError("network on fire")

    version.latest_release = explode
    try:
        version.check_for_update()
    except RuntimeError:
        raise AssertionError("check_for_update must absorb lookup failures, not propagate them")
    except Exception:
        pass
    finally:
        version.latest_release = original


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    failures = []
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failures.append(f"{test.__name__}: {exc}")
    if failures:
        print("VERSION-TESTS FAILED:")
        for failure in failures:
            print("  -", failure)
        return 1
    print(f"ALL-VERSION-TESTS-PASS ({len(tests)} checks, version {version.VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
