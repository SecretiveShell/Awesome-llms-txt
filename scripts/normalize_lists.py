#!/usr/bin/env python3
"""Normalize README entries and regenerate JSON URL lists."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
JSON_DIR = ROOT / "json"
LLMS_TXT_JSON = JSON_DIR / "llms-txt.json"
LLMS_FULL_JSON = JSON_DIR / "llms-full.json"
URLS_JSON = JSON_DIR / "urls.json"

ENTRY_RE = re.compile(r"^\s*-\s+\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)\s*$")
TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "srsltid",
}


@dataclass(frozen=True)
class Entry:
    url: str
    label: str
    is_full: bool


def clean_url(raw_url: str) -> str:
    """Return a stable URL key/output value for an llms list entry."""
    raw_url = raw_url.strip()
    parts = urlsplit(raw_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"Unsupported URL: {raw_url}")

    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    if not hostname:
        raise ValueError(f"Unsupported URL: {raw_url}")

    netloc = hostname
    if parts.port and not (
        (scheme == "https" and parts.port == 443)
        or (scheme == "http" and parts.port == 80)
    ):
        netloc = f"{netloc}:{parts.port}"

    query_items = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS and not key.lower().startswith("utm_")
    ]
    query = urlencode(query_items, doseq=True)

    return urlunsplit((scheme, netloc, parts.path or "/", query, ""))


def label_for_url(url: str) -> str:
    parts = urlsplit(url)
    label = parts.netloc.lower()
    if is_full_url(url):
        return f"{label} (full)"
    return label


def is_full_url(url: str) -> bool:
    return urlsplit(url).path.lower().endswith("llms-full.txt")


def split_readme(markdown: str) -> tuple[str, list[str], str]:
    lines = markdown.splitlines()
    first_entry = None
    for index, line in enumerate(lines):
        if ENTRY_RE.match(line):
            first_entry = index
            break

    if first_entry is None:
        raise ValueError("No Markdown list entries found in README.md")

    end_entry = len(lines)
    for index in range(first_entry, len(lines)):
        if index > first_entry and lines[index].startswith("## "):
            end_entry = index
            break

    prefix = "\n".join(lines[:first_entry]).rstrip()
    entry_lines = lines[first_entry:end_entry]
    suffix = "\n".join(lines[end_entry:]).rstrip()
    return prefix, entry_lines, suffix


def parse_entries(lines: list[str]) -> list[Entry]:
    entries: dict[str, Entry] = {}

    for line in lines:
        if not line.strip():
            continue
        match = ENTRY_RE.match(line)
        if not match:
            raise ValueError(f"Malformed list entry: {line}")

        url = clean_url(match.group("url"))
        entries[url] = Entry(url=url, label=label_for_url(url), is_full=is_full_url(url))

    return sorted(
        entries.values(),
        key=lambda entry: (
            entry.label.removesuffix(" (full)"),
            0 if entry.is_full else 1,
            entry.url,
        ),
    )


def render_readme(prefix: str, entries: list[Entry], suffix: str) -> str:
    rendered_entries = "\n".join(f"- [{entry.label}]({entry.url})" for entry in entries)
    parts = [prefix, rendered_entries]
    if suffix:
        parts.append(suffix)
    return "\n\n".join(parts).rstrip() + "\n"


def render_json(urls: list[str]) -> str:
    return json.dumps(urls, indent=4) + "\n"


def build_outputs() -> dict[Path, str]:
    prefix, raw_entries, suffix = split_readme(README.read_text(encoding="utf-8"))
    entries = parse_entries(raw_entries)
    llms_full_urls = [entry.url for entry in entries if entry.is_full]
    llms_txt_urls = [entry.url for entry in entries if not entry.is_full]
    all_urls = [entry.url for entry in entries]

    return {
        README: render_readme(prefix, entries, suffix),
        LLMS_TXT_JSON: render_json(llms_txt_urls),
        LLMS_FULL_JSON: render_json(llms_full_urls),
        URLS_JSON: render_json(all_urls),
    }


def write_outputs(outputs: dict[Path, str]) -> None:
    for path, contents in outputs.items():
        path.write_text(contents, encoding="utf-8")


def check_outputs(outputs: dict[Path, str]) -> int:
    failed = False
    for path, expected in outputs.items():
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            print(f"{path.relative_to(ROOT)} is not normalized", file=sys.stderr)
            failed = True
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize README.md and regenerate JSON URL lists."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report files that need normalization without writing changes",
    )
    args = parser.parse_args()

    outputs = build_outputs()
    if args.check:
        return check_outputs(outputs)

    write_outputs(outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
