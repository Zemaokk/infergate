"""Check repository Markdown navigation and the dated documentation archive.

Uses only the standard library; remote URLs are deliberately not fetched.
Run from any directory: python scripts/check_docs.py
"""

import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "docs/archive/2026-10-08"


def prose(text):
    """Ignore fenced/inline code and HTML comments when extracting navigation."""
    lines = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            run = marker[1]
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line)
    text = re.sub(r"<!--.*?-->", "", "\n".join(lines), flags=re.S)
    return text


def anchors(text):
    result = set(re.findall(r'''\b(?:id|name)=["']([^"']+)["']''', text))
    counts = Counter()
    for heading in re.findall(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        heading = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
        heading = html.unescape(re.sub(r"<[^>]+>", "", heading)).lower()
        slug = re.sub(r"[^\w\-\s]", "", heading).replace(" ", "-")
        suffix = counts[slug]
        counts[slug] += 1
        result.add(slug if suffix == 0 else f"{slug}-{suffix}")
    return result


def links(text):
    definitions = {}
    for label, target in re.findall(r"^\s{0,3}\[([^\]]+)\]:\s*(<[^>]+>|\S+)", text, re.M):
        definitions[" ".join(label.lower().split())] = target.strip("<>")
    # Code literals may contain bracketed protocol examples such as [DONE].
    text = re.sub(r"(`+).*?\1", "", text)
    targets = re.findall(r"!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)", text)
    targets += re.findall(r'''\b(?:href|src)=["']([^"']+)["']''', text)
    for label, reference in re.findall(r"!?\[([^\]\n]+)\]\[([^\]\n]*)\]", text):
        key = " ".join((reference or label).lower().split())
        if key not in definitions:
            raise ValueError(f"undefined link reference [{reference or label}]")
        targets.append(definitions[key])
    # Include shortcut reference links only when a definition exists.
    for label in re.findall(r"(?<!!)\[([^\]\n]+)\](?![(:\[])", text):
        key = " ".join(label.lower().split())
        if key in definitions:
            targets.append(definitions[key])
    return [html.unescape(target.strip("<>")) for target in targets]


def check_navigation():
    paths = sorted(set([*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md"),
                        ROOT / "observability/README.md", ROOT / "scripts/m4_benchmark/README.md"]))
    errors = []
    cache = {}
    count = 0
    for path in paths:
        try:
            targets = links(prose(path.read_text()))
        except ValueError as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
            continue
        for target in targets:
            url = urlsplit(target)
            if url.scheme or url.netloc:
                continue
            count += 1
            destination = ((ROOT if url.path.startswith("/") else path.parent)
                           / unquote(url.path).lstrip("/")).resolve() if url.path else path
            if not destination.exists():
                errors.append(f"{path.relative_to(ROOT)}: missing target {target}")
            elif url.fragment and destination.suffix.lower() == ".md":
                if destination not in cache:
                    cache[destination] = anchors(prose(destination.read_text()))
                if unquote(url.fragment) not in cache[destination]:
                    errors.append(f"{path.relative_to(ROOT)}: missing anchor {target}")
    return errors, len(paths), count


def check_archive():
    manifest = json.loads((ARCHIVE / "manifest.json").read_text())
    errors = []
    for item in manifest["files"]:
        path = ROOT / item["archived_path"]
        if not path.is_file():
            errors.append(f"archive file missing: {item['archived_path']}")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["archived_sha256"]:
            errors.append(f"archive content changed: {item['archived_path']}")
        if path.suffix.lower() != ".md" and digest != item["original_sha256"]:
            errors.append(f"non-Markdown evidence differs: {item['archived_path']}")
    current_plot = ROOT / "docs/M4/benchmark-real-20261007/real-comparison.png"
    old_plot = ARCHIVE / "docs/M4/benchmark-real-20261007/real-comparison.png"
    if current_plot.read_bytes() != old_plot.read_bytes():
        errors.append("README compatibility plot differs from archived original")
    return errors, len(manifest["files"])


def main():
    errors, pages, local_links = check_navigation()
    archive_errors, files = check_archive()
    errors.extend(archive_errors)
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Documentation OK: {pages} Markdown pages, {local_links} local links, "
          f"{files} archived files verified")


if __name__ == "__main__":
    main()
