"""llmwiki/ stays a conformant Open Knowledge Format (OKF) v0.2 bundle.

The rules enforced here are owned by ``llmwiki/_conventions.md`` (section
"Index, log and validation"). This test needs no OKF tooling, so the bundle's
conformance is gated in the normal pytest run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WIKI = REPO_ROOT / "llmwiki"
RESERVED = {"index.md", "log.md"}
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
ENTRY = re.compile(r"^\* \[[^\]]+\]\(([^)\s]+)\) - (.+)$", re.MULTILINE)
LINK = re.compile(r"\]\(([^)\s]+?)(?:#[^)]*)?\)")
FENCE = re.compile(r"^(`{3,}).*?^\1", re.DOTALL | re.MULTILINE)
REQUIRED_KEYS = {
    "type",
    "title",
    "description",
    "canonical-for",
    "sources",
    "verified-against",
    "last-verified",
}


def _concept_types() -> set[str]:
    """The closed type vocabulary, read from the conventions page that owns it."""
    text = (WIKI / "_conventions.md").read_text(encoding="utf-8")
    table = text.split("#### Concept types", 1)[1].split("\n#", 1)[0]
    return set(re.findall(r"^\| `([A-Za-z ]+)` \|", table, re.MULTILINE))


def _concepts() -> list[Path]:
    return sorted(p for p in WIKI.rglob("*.md") if p.name not in RESERVED)


def _front_matter(path: Path) -> dict:
    match = FRONT_MATTER.match(path.read_text(encoding="utf-8"))
    assert match, f"{path.relative_to(WIKI)}: missing YAML front matter"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict), (
        f"{path.relative_to(WIKI)}: front matter is not a mapping"
    )
    return data


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[*`_\"']", "", text).lower().split()).rstrip(".")


@pytest.mark.parametrize("page", _concepts(), ids=lambda p: str(p.relative_to(WIKI)))
def test_concept_front_matter(page: Path) -> None:
    """Every page carries the OKF keys and this wiki's own schema keys."""
    data = _front_matter(page)
    assert REQUIRED_KEYS <= data.keys(), REQUIRED_KEYS - data.keys()
    assert data["type"] in _concept_types()
    body = FRONT_MATTER.sub("", page.read_text(encoding="utf-8"), count=1)
    heading = re.search(r"^# (.+)$", body, re.MULTILINE)
    assert heading and heading.group(1).strip() == data["title"]
    assert isinstance(data["sources"], list) and data["sources"]
    for source in data["sources"]:
        assert isinstance(source, dict) and str(source.get("resource", "")).strip()


@pytest.mark.parametrize("page", _concepts(), ids=lambda p: str(p.relative_to(WIKI)))
def test_concept_listed_in_parent_index(page: Path) -> None:
    """Each page appears in its directory's index.md with its own description."""
    index = page.parent / "index.md"
    assert index.exists(), f"{index.relative_to(WIKI)} is missing"
    entries = {
        (index.parent / href).resolve(): desc
        for href, desc in ENTRY.findall(index.read_text(encoding="utf-8"))
    }
    assert page.resolve() in entries, f"not listed in {index.relative_to(WIKI)}"
    description = _normalize(_front_matter(page)["description"])
    assert description in _normalize(entries[page.resolve()])


def test_index_files_follow_okf() -> None:
    """Only the root index has front matter, and it holds only okf_version."""
    root = WIKI / "index.md"
    match = FRONT_MATTER.match(root.read_text(encoding="utf-8"))
    assert match and yaml.safe_load(match.group(1)) == {"okf_version": "0.2"}
    chapters = sorted(p for p in WIKI.iterdir() if p.is_dir())
    assert chapters
    root_targets = {
        (WIKI / href).resolve()
        for href, _ in ENTRY.findall(root.read_text(encoding="utf-8"))
    }
    for chapter in chapters:
        index = chapter / "index.md"
        assert not FRONT_MATTER.match(index.read_text(encoding="utf-8")), index
        assert index.resolve() in root_targets, f"{chapter.name}/ not in root index"


def test_log_follows_okf() -> None:
    """log.md: no front matter, ISO date groups newest first, one op per entry."""
    text = (WIKI / "log.md").read_text(encoding="utf-8")
    assert not FRONT_MATTER.match(text)
    body = FENCE.sub("", text)
    dates = re.findall(r"^## (.+)$", body, re.MULTILINE)
    assert dates
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in dates), dates
    assert dates == sorted(dates, reverse=True), "date groups must be newest first"
    assert len(dates) == len(set(dates)), "one heading per date"
    ops = re.findall(r"^### (\w+) \| \S", body, re.MULTILINE)
    assert len(ops) == len(re.findall(r"^### ", body, re.MULTILINE))
    vocabulary = set(
        re.findall(r"`(\w+)`:", body.split("**Operations.**", 1)[1].split("\n\n", 1)[0])
    )
    assert set(ops) <= vocabulary, set(ops) - vocabulary


def test_relative_links_resolve() -> None:
    """Every relative link in the wiki points at an existing file or directory."""
    broken = []
    for page in sorted(WIKI.rglob("*.md")):
        body = FENCE.sub("", page.read_text(encoding="utf-8"))
        body = re.sub(r"`[^`\n]*`", "", body)
        for href in LINK.findall(body):
            if "://" in href or href.startswith(("mailto:", "#")):
                continue
            if not (page.parent / href).exists():
                broken.append(f"{page.relative_to(WIKI)} -> {href}")
    assert broken == []
