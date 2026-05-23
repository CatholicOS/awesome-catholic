#!/usr/bin/env python3
"""Discover candidate Catholic projects on GitHub for the awesome-catholic list.

Runs a set of GitHub searches (see ``keywords.txt``), drops anything already
linked from ``README.md``, applies basic quality filters (stars, recency,
archived/fork status), and prints the remaining candidates as a Markdown
review list or as JSON.

Requires the GitHub CLI (`gh`) to be installed and authenticated.

Examples:
    ./scripts/discover.py                       # Markdown report, default filters
    ./scripts/discover.py --min-stars 5         # only repos with >=5 stars
    ./scripts/discover.py --format json         # machine-readable, for the agent
    ./scripts/discover.py --inactive-months 36  # widen the recency window
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_README = REPO_ROOT / "README.md"
DEFAULT_KEYWORDS = Path(__file__).resolve().parent / "keywords.txt"

# Matches the owner/repo of any github.com link, ignoring the scheme and any
# trailing path, query string, ".git" suffix or punctuation.
GH_LINK_RE = re.compile(
    r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.IGNORECASE
)

# JSON fields requested from `gh search repos`.
GH_FIELDS = "fullName,description,stargazersCount,updatedAt,language,url,isArchived,isFork"


def load_keywords(path: Path) -> list[str]:
    keywords: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keywords.append(line)
    return keywords


def normalize_repo(full_name: str) -> str:
    """Normalize an ``owner/repo`` string for set comparison."""
    name = full_name.strip().lower().rstrip("/")
    if name.endswith(".git"):
        name = name[:-4]
    # A bare github.com link without a repo path won't have a slash; guard it.
    return name


def existing_repos(readme: Path) -> set[str]:
    """Return the set of ``owner/repo`` already linked from the README."""
    text = readme.read_text(encoding="utf-8")
    found: set[str] = set()
    for match in GH_LINK_RE.findall(text):
        repo = normalize_repo(match)
        # Skip links to GitHub itself or to non-repo pages (e.g. /topics/...).
        owner, _, name = repo.partition("/")
        if owner in {"topics", "sponsors", "marketplace", "features"} or not name:
            continue
        found.add(repo)
    return found


def gh_search(query: str, limit: int, sort: str) -> list[dict]:
    """Run a single `gh search repos` query and return parsed JSON results."""
    cmd = [
        "gh", "search", "repos", query,
        "--limit", str(limit),
        "--sort", sort,
        "--json", GH_FIELDS,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=60
        )
    except FileNotFoundError:
        sys.exit("error: the GitHub CLI (`gh`) is not installed or not on PATH.")
    except subprocess.TimeoutExpired:
        print(f"  warning: query timed out: {query!r}", file=sys.stderr)
        return []
    except subprocess.CalledProcessError as exc:
        print(f"  warning: query failed ({query!r}): {exc.stderr.strip()}",
              file=sys.stderr)
        return []
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []


def parse_updated(value: str) -> datetime | None:
    if not value:
        return None
    try:
        # gh returns RFC3339 timestamps, e.g. "2025-12-10T08:30:00Z".
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def discover(args: argparse.Namespace) -> list[dict]:
    keywords = load_keywords(args.keywords)
    already = existing_repos(args.readme)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * args.inactive_months)

    candidates: dict[str, dict] = {}
    for query in keywords:
        if not args.quiet:
            print(f"searching: {query}", file=sys.stderr)
        for repo in gh_search(query, args.limit, args.sort):
            full = repo.get("fullName", "")
            key = normalize_repo(full)
            if not key or "/" not in key:
                continue
            if key in already or key in candidates:
                continue
            if args.no_archived and repo.get("isArchived"):
                continue
            if args.no_forks and repo.get("isFork"):
                continue
            if (repo.get("stargazersCount") or 0) < args.min_stars:
                continue
            updated = parse_updated(repo.get("updatedAt", ""))
            if updated and updated < cutoff:
                continue
            repo["_matchedQuery"] = query
            candidates[key] = repo

    results = list(candidates.values())
    results.sort(key=lambda r: r.get("stargazersCount") or 0, reverse=True)
    return results


def render_markdown(results: list[dict]) -> str:
    if not results:
        return "No new candidate projects found."
    lines = [
        f"## Candidate Catholic projects ({len(results)} found)",
        "",
        "Review each below; check off the ones worth adding to the list.",
        "",
    ]
    for r in results:
        stars = r.get("stargazersCount") or 0
        lang = r.get("language") or "—"
        desc = (r.get("description") or "").strip() or "_(no description)_"
        updated = (r.get("updatedAt") or "")[:10]
        lines.append(
            f"- [ ] [{r['fullName']}]({r['url']}) — ⭐ {stars} · {lang} · "
            f"updated {updated} · matched `{r['_matchedQuery']}`\n"
            f"      {desc}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README,
                        help="path to the list README (default: repo README.md)")
    parser.add_argument("--keywords", type=Path, default=DEFAULT_KEYWORDS,
                        help="path to the keywords file")
    parser.add_argument("--limit", type=int, default=40,
                        help="max results per query (default: 40)")
    parser.add_argument("--sort", choices=["stars", "updated", "forks", "best-match"],
                        default="stars",
                        help="how `gh` ranks each query's results (default: stars)")
    parser.add_argument("--min-stars", type=int, default=2,
                        help="minimum stars to include (default: 2)")
    parser.add_argument("--inactive-months", type=int, default=24,
                        help="drop repos not updated within this many months (default: 24)")
    parser.add_argument("--no-archived", action="store_true", default=True,
                        help="exclude archived repos (default: on)")
    parser.add_argument("--include-archived", dest="no_archived",
                        action="store_false", help="include archived repos")
    parser.add_argument("--no-forks", action="store_true", default=True,
                        help="exclude forks (default: on)")
    parser.add_argument("--include-forks", dest="no_forks",
                        action="store_false", help="include forks")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown",
                        help="output format (default: markdown)")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress progress output on stderr")
    args = parser.parse_args()

    if not args.readme.exists():
        sys.exit(f"error: README not found at {args.readme}")
    if not args.keywords.exists():
        sys.exit(f"error: keywords file not found at {args.keywords}")

    results = discover(args)

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        print(render_markdown(results))


if __name__ == "__main__":
    main()
