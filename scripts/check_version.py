"""Check that the release version is the same everywhere.

    python scripts/check_version.py                 # the manifests and CHANGELOG.md
    python scripts/check_version.py --tag v0.1.0    # and a release tag
    python scripts/check_version.py --notes         # print the version's changelog section

The version lives in the API (``api/pyproject.toml`` and ``arena.__version__``, which
``/api/version`` reports), the client (``client/pyproject.toml`` and
``jackdaw_arena.__version__``) and the site (``web/package.json``), and CHANGELOG.md needs a
``## [X.Y.Z]`` section for it. CI runs this; the Release workflow also checks the tag it drafts.
Exits 1 on a mismatch. Python 3.11+, no dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _toml(path: str) -> str:
    return tomllib.loads((ROOT / path).read_text(encoding="utf-8"))["project"]["version"]


def _dunder(path: str) -> str:
    found = re.search(r'^__version__ = "([^"]+)"', (ROOT / path).read_text(encoding="utf-8"), re.M)
    return found.group(1) if found else "(none)"


def manifest_versions() -> dict[str, str]:
    return {
        "api/pyproject.toml": _toml("api/pyproject.toml"),
        "api/src/arena/__init__.py": _dunder("api/src/arena/__init__.py"),
        "client/pyproject.toml": _toml("client/pyproject.toml"),
        "client/src/jackdaw_arena/__init__.py": _dunder("client/src/jackdaw_arena/__init__.py"),
        "web/package.json": json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))[
            "version"
        ],
    }


def changelog_section(version: str) -> str | None:
    """The body of CHANGELOG.md's section for ``version``, or None."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n", re.MULTILINE)
    found = heading.search(text)
    if found is None:
        return None
    rest = text[found.end() :]
    following = re.search(r"^## ", rest, re.MULTILINE)
    return (rest[: following.start()] if following else rest).strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--tag", help="a release tag (vX.Y.Z) that must name the version")
    p.add_argument("--notes", action="store_true", help="print the version's changelog section")
    args = p.parse_args(argv)

    found = manifest_versions()
    version = found["api/pyproject.toml"]
    errors = []
    if len(set(found.values())) != 1:
        errors.append("the manifests disagree: " + ", ".join(f"{k} {v}" for k, v in found.items()))
    notes = changelog_section(version)
    if notes is None:
        errors.append(f"CHANGELOG.md has no '## [{version}]' section")
    if args.tag is not None and args.tag != f"v{version}":
        errors.append(f"the tag {args.tag} doesn't name the version {version} (v{version})")
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    if errors:
        return 1
    if args.notes:
        print(notes, end="")
    else:
        print(f"version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
