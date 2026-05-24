#!/usr/bin/env python3
"""Audit the awesome-catholic list for staleness, in both directions.

For every entry it checks the backing GitHub/Codeberg repo's last push date
(via the REST APIs, token from GH_TOKEN/GITHUB_TOKEN) and proposes:

  - active section -> Attic   when a repo is archived or hasn't been pushed
                              in `--months` months (default 36);
  - Attic -> origin section   when an attic'd repo has become active again.

To make revival deterministic, entries moved to the Attic carry an
``<!-- origin: <Section> -->`` marker recording where they came from.

Website / app-store entries are *not* moved automatically (liveness checks
are too prone to false negatives from bot-blocking); they are only flagged
for human review.

Usage:
    ./scripts/audit.py            # report proposed moves (no changes)
    ./scripts/audit.py --apply    # perform the repo moves in README.md
    ./scripts/audit.py --months 24 --format json

Exit codes: 0 ok; 1 fatal (no token / missing file); 2 some checks failed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_README = REPO_ROOT / "README.md"

IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
GH = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.I)
CB = re.compile(r"codeberg\.org/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.I)
ORIGIN = re.compile(r"\s*<!--\s*origin:\s*(.+?)\s*-->\s*$")

ATTIC = "Attic"
# Sections whose entries are never auto-moved into the Attic by age.
EXCLUDE = {"Contents", ATTIC, "Christian and Faith-Related", "Catholic-adjacent"}


def token():
    """A GitHub token from the environment, the gh CLI, or git's credential
    helper — so the script self-authenticates wherever credentials exist."""
    env = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if env:
        return env
    try:
        p = subprocess.run(["gh", "auth", "token"], capture_output=True,
                            text=True, timeout=10)
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    except Exception:
        pass
    try:
        p = subprocess.run(["git", "credential", "fill"], capture_output=True,
                           text=True, timeout=10,
                           input="protocol=https\nhost=github.com\n\n")
        for line in p.stdout.splitlines():
            if line.startswith("password="):
                return line[len("password="):] or None
    except Exception:
        pass
    return None


def api_get(url):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "awesome-catholic-audit")
    req.add_header("Accept", "application/vnd.github+json")
    if token() and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {token()}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def primary(line):
    """Return (identifier, name, url) for the entry's main link, badges stripped."""
    m = LINK.search(IMG.sub("", line[2:]))
    if not m:
        return None, None, None
    name, url = m.group(1), m.group(2)
    g, c = GH.search(url), CB.search(url)
    if g:
        return "gh:" + g.group(1).removesuffix(".git").lower(), name, url
    if c:
        return "cb:" + c.group(1).removesuffix(".git").lower(), name, url
    return "url:" + url.lower().rstrip("/"), name, url


def repo_status(ident):
    """Return (pushed: datetime|None, archived: bool, ok: bool)."""
    host, repo = ident.split(":", 1)
    try:
        if host == "gh":
            d = api_get(f"https://api.github.com/repos/{repo}")
        else:
            d = api_get(f"https://codeberg.org/api/v1/repos/{repo}")
    except Exception:
        return None, False, False
    ts = d.get("pushed_at") or d.get("updated_at") or ""
    try:
        pushed = datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None
    except ValueError:
        pushed = None
    return pushed, bool(d.get("archived")), True


def read_origin(line):
    m = ORIGIN.search(line)
    return m.group(1) if m else None


def strip_origin(line):
    return ORIGIN.sub("", line).rstrip()


def add_origin(line, section):
    return f"{strip_origin(line)} <!-- origin: {section} -->"


def detect(lines, months, revive_months):
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=int(months * 30.44))
    revive_cutoff = now - timedelta(days=int(revive_months * 30.44))
    section = None
    to_attic, revive, flags, errors, sites = {}, {}, [], 0, 0
    for line in lines:
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.startswith("- "):
            continue
        ident, name, _ = primary(line)
        if not ident:
            continue
        if ident.startswith("url:"):
            # Websites/apps are not auto-checked: link reachability from the
            # run environment is unreliable (sandboxed DNS/network), so it must
            # not drive classification. They are curated by hand; we only count
            # them here so they're acknowledged, not silently ignored.
            sites += 1
            continue
        pushed, archived, ok = repo_status(ident)
        if not ok:
            errors += 1
            continue
        stale = archived or (pushed is not None and pushed < stale_cutoff)
        if section == ATTIC:
            # Hysteresis: only revive on genuine recent activity, not merely
            # being under the staleness line — avoids boundary flapping.
            if not archived and pushed is not None and pushed >= revive_cutoff:
                origin = read_origin(line)
                if origin:
                    revive[ident] = (origin, name, pushed)
                else:
                    flags.append(f"{name}: revivable but has no origin tag")
        elif section not in EXCLUDE:
            if stale:
                to_attic[ident] = (section, name,
                                   "archived" if archived else
                                   (pushed.date().isoformat() if pushed else "?"))
    return to_attic, revive, flags, errors, sites


def section_end(lines, section):
    """Index just past the last content line of ``section`` (insertion point)."""
    start = next((i for i, row in enumerate(lines)
                  if row.startswith("## ") and row[3:].strip() == section), None)
    if start is None:
        return None
    i = start + 1
    last = start
    while i < len(lines) and not lines[i].startswith("## "):
        if lines[i].strip():
            last = i
        i += 1
    return last + 1


def apply_moves(lines, to_attic, revive):
    moved_attic, moved_back = [], {}
    kept = []
    section = None
    for line in lines:
        if line.startswith("## "):
            section = line[3:].strip()
            kept.append(line)
            continue
        if line.startswith("- "):
            ident, _, _ = primary(line)
            if section != ATTIC and ident in to_attic:
                moved_attic.append(add_origin(line, section))
                continue
            if section == ATTIC and ident in revive:
                origin = revive[ident][0]
                moved_back.setdefault(origin, []).append(strip_origin(line))
                continue
        kept.append(line)

    lines = kept
    # Revive first (sections still intact), then append to Attic.
    for origin, entries in moved_back.items():
        idx = section_end(lines, origin)
        if idx is not None:
            lines[idx:idx] = entries
    idx = section_end(lines, ATTIC)
    if idx is not None:
        lines[idx:idx] = moved_attic
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--readme", type=Path, default=DEFAULT_README)
    ap.add_argument("--months", type=float, default=36,
                    help="inactivity months before an active entry is attic'd (default: 36)")
    ap.add_argument("--revive-months", type=float, default=12,
                    help="recent-activity months for an attic entry to be revived (default: 12)")
    ap.add_argument("--apply", action="store_true",
                    help="perform the repo moves in README.md")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    if not args.readme.exists():
        sys.exit(f"error: README not found at {args.readme}")
    if not token():
        sys.exit("error: set GH_TOKEN or GITHUB_TOKEN (GitHub API requires auth).")

    lines = args.readme.read_text(encoding="utf-8").split("\n")
    to_attic, revive, flags, errors, sites = detect(
        lines, args.months, args.revive_months)

    if args.format == "json":
        print(json.dumps({
            "to_attic": {k: {"from": v[0], "name": v[1], "last": v[2]}
                         for k, v in to_attic.items()},
            "revive": {k: {"to": v[0], "name": v[1]} for k, v in revive.items()},
            "flags": flags, "check_errors": errors, "sites_unchecked": sites,
        }, indent=2))
    else:
        print(f"## Stale -> Attic ({len(to_attic)})")
        for sec, name, last in to_attic.values():
            print(f"  - {name} [{sec}] last activity {last}")
        print(f"\n## Attic -> active ({len(revive)})")
        for sec, name, pushed in revive.values():
            print(f"  - {name} -> {sec} (pushed {pushed.date()})")
        if flags:
            print(f"\n## Flagged for manual review ({len(flags)})")
            for f in flags:
                print(f"  - {f}")
        print(f"\n{sites} website/app entries not auto-checked (curate by hand).")
        if errors:
            print(f"{errors} repo check(s) failed.")

    if args.apply:
        new = apply_moves(lines, to_attic, revive)
        args.readme.write_text("\n".join(new), encoding="utf-8")
        print(f"\napplied: {len(to_attic)} -> Attic, {len(revive)} revived.",
              file=sys.stderr)

    sys.exit(2 if errors else 0)


if __name__ == "__main__":
    main()
