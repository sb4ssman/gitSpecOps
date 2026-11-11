"""The network map's policy lives in Python: shared copies between machines, and whether they agree.

Synthetic manifests only. The skin draws `map.links` and `row.copies`; it never works them out.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bootstrap import setup  # noqa: E402

setup()

from Elaborate._fleet.display import build_display  # noqa: E402
from Special._sync.manifest import build_manifest, fleet_id_for  # noqa: E402

SECRET = "33" * 32
FLEET = fleet_id_for(SECRET)
NAMES = {"a" * 32: {"host": "github.com", "owner": "example", "name": "shared"},
         "b" * 32: {"host": "github.com", "owner": "example", "name": "only-one"}}


def repo(repo_id, head, dirty=0):
    return {"repo_id": repo_id, "branch_id": "d" * 16, "has_upstream": True,
            "upstream_observed_at": None, "ahead": 0, "behind": 0, "staged": 0,
            "unstaged": dirty, "untracked": 0, "stashes": 0, "operation": None,
            "branch": "main", "head": head}


def report(machine, repositories):
    return {"manifest": build_manifest(FLEET, machine, machine, repositories, carries_names=True),
            "names": NAMES, "issues": []}


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def rows_by_name(document):
    return {row["name"]: row for row in document["rows"]}


def test_links_count_shared_copies_and_disagreement():
    document = build_display([report("one", [repo("a" * 32, "1" * 40), repo("b" * 32, "2" * 40)]),
                              report("two", [repo("a" * 32, "9" * 40)])], FLEET)
    links = document["map"]["links"]
    check(len(links) == 1, links)
    link = links[0]
    check({link["a"], link["b"]} == {"one", "two"}, link)
    check(link["shared"] == 1 and link["differ"] == 1, link)


def test_copies_agree_only_when_every_copy_shares_its_commit():
    same = build_display([report("one", [repo("a" * 32, "1" * 40)]),
                          report("two", [repo("a" * 32, "1" * 40)])], FLEET)
    check(rows_by_name(same)["example/shared"]["copies"] == {"present": 2, "heads_agree": True},
          rows_by_name(same)["example/shared"]["copies"])
    check(same["map"]["links"][0]["differ"] == 0, same["map"]["links"])
    withheld = build_display([report("one", [repo("a" * 32, "1" * 40)]),
                              report("two", [repo("a" * 32, None)])], FLEET)
    check(rows_by_name(withheld)["example/shared"]["copies"]["heads_agree"] is None,
          "a withheld commit proves nothing; agreement is unknown")


def test_machines_with_nothing_in_common_are_not_linked():
    document = build_display([report("one", [repo("a" * 32, "1" * 40)]),
                              report("two", [repo("b" * 32, "2" * 40)])], FLEET)
    check(document["map"]["links"] == [], document["map"]["links"])
    check(document["contract"]["version"] == 1, "the map is additive: the contract stays v1")


def main():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL-NETWORK-MAP-TESTS-PASS ({len(tests)} checks)")


if __name__ == "__main__":
    main()
