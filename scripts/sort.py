#!/usr/bin/env python3
"""Re-badge and re-order the awesome-catholic list by star count.

Adds a live star badge to every code-repo entry (after its language badge, if
any) and sorts each section by stars descending, placing non-repo
(website/app) entries after the repos. Idempotent — re-running only refreshes
the ordering as star counts change and badges any newly-added repos.

Token resolution (for the star counts): GH_TOKEN / GITHUB_TOKEN, then the gh
CLI, then git's credential helper.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_README = REPO_ROOT / "README.md"

IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
GH = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.I)
CB = re.compile(r"codeberg\.org/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.I)
# leading "- " + an optional single image badge (the language badge)
HEAD = re.compile(r"^(- )(!\[[^\]]*\]\([^)]*\) )?(.*)$", re.S)


@functools.lru_cache(maxsize=1)
def token():
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


def api(url):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "awesome-catholic-sort")
    if token() and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {token()}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def repo_of(line):
    m = LINK.search(IMG.sub("", line[2:]))
    if not m:
        return None
    g, c = GH.search(m.group(2)), CB.search(m.group(2))
    if g:
        return "gh", g.group(1), g.group(2).removesuffix(".git")
    if c:
        return "cb", c.group(1), c.group(2).removesuffix(".git")
    return None


_stars = {}
def stars(host, owner, repo):
    """Current star count, or None if the lookup failed — kept distinct from a
    real 0 so a network/rate-limit error can't silently re-order a repo."""
    key = (host, owner.lower(), repo.lower())
    if key in _stars:
        return _stars[key]
    try:
        if host == "gh":
            n = api(f"https://api.github.com/repos/{owner}/{repo}").get("stargazers_count", 0)
        else:
            n = api(f"https://codeberg.org/api/v1/repos/{owner}/{repo}").get("stars_count", 0)
    except Exception:
        n = None
    _stars[key] = n
    return n


# shields.io treats a trailing .svg/.json/.png/... in the path as a format
# extension, which breaks the live github/stars badge for repos whose name ends
# that way (e.g. "summa.json"). Those fall back to a static count badge instead.
BAD_EXT = (".svg", ".json", ".png", ".jpg", ".jpeg", ".gif")
STAR = re.compile(r"!\[⭐\]\([^)]*\)\s*")
LANG = re.compile(r"(!\[[^\]]*\]\([^)]*\) )(.*)$", re.S)


def star_badge(host, owner, repo, count):
    if repo.lower().endswith(BAD_EXT):
        n = count if count is not None else 0
        return f"![⭐](https://img.shields.io/badge/%E2%AD%90-{n}-blue)"
    if host == "gh":
        url = f"https://img.shields.io/github/stars/{owner}/{repo}?label=%E2%AD%90"
    else:
        url = (f"https://img.shields.io/gitea/stars/{owner}/{repo}"
               "?gitea_url=https%3A%2F%2Fcodeberg.org&label=%E2%AD%90")
    return f"![⭐]({url})"


def add_badge(line, host, owner, repo, count):
    """(Re)build the star badge: strip any existing one, then insert a fresh
    badge after the language badge (if any). Regenerating keeps static counts
    current and is a no-op for dynamic badges."""
    body = STAR.sub("", line[2:])
    star = star_badge(host, owner, repo, count)
    m = LANG.match(body)
    if m:
        return f"- {m.group(1)}{star} {m.group(2)}"
    return f"- {star} {body}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--readme", type=Path, default=DEFAULT_README)
    args = ap.parse_args()

    lines = args.readme.read_text(encoding="utf-8").split("\n")
    head, sections, cur = [], [], None
    for line in lines:
        if line.startswith("## "):
            cur = [line, []]
            sections.append(cur)
        elif cur is None:
            head.append(line)
        else:
            cur[1].append(line)

    out, n_badged, failed = list(head), 0, []
    for header, body in sections:
        i = 0
        # preamble = non-blank lines before the first bullet (e.g. a section
        # description); preserved so nothing is silently dropped.
        preamble = []
        while i < len(body) and not body[i].startswith("- "):
            if body[i].strip():
                preamble.append(body[i])
            i += 1
        # items = a bullet line plus its continuation lines
        items = []
        while i < len(body):
            if body[i].startswith("- "):
                item = [body[i]]
                i += 1
                while i < len(body) and body[i].strip() and not body[i].startswith("- "):
                    item.append(body[i]); i += 1
                items.append(item)
            else:
                i += 1

        decorated = []
        for idx, item in enumerate(items):
            r = repo_of(item[0])
            if r:
                s = stars(*r)
                if s is None:
                    failed.append(f"{r[1]}/{r[2]}")
                badged = add_badge(item[0], *r, s)
                if badged != item[0]:
                    n_badged += 1
                item[0] = badged
                key = (0, -(s or 0), idx)   # repos first, stars desc
            else:
                key = (1, 0, idx)           # non-repo entries after, stable
            decorated.append((key, item))
        decorated.sort(key=lambda d: d[0])

        out.append(header)
        out.append("")
        out.extend(preamble)
        if preamble:
            out.append("")
        for _, item in decorated:
            out.extend(item)
        out.append("")

    if failed:
        sys.exit(f"error: star lookup failed for {len(failed)} repo(s) "
                 f"({', '.join(failed[:5])}{'…' if len(failed) > 5 else ''}); "
                 "aborting without re-sorting to avoid mis-ordering.")

    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).rstrip() + "\n"
    args.readme.write_text(text, encoding="utf-8")
    print(f"re-sorted {len(sections)} sections; added {n_badged} new star badge(s)")


if __name__ == "__main__":
    main()
