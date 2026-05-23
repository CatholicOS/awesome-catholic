#!/usr/bin/env python3
"""Discover candidate Catholic projects on GitHub for the awesome-catholic list.

Runs a set of GitHub searches (see ``keywords.txt``), drops anything already
linked from ``README.md`` *or* already proposed in an open pull request,
applies basic quality filters (stars, recency, archived/fork status), and
prints the remaining candidates as a Markdown review list or as JSON.

Requires the GitHub CLI (`gh`) to be installed and authenticated. `gh` reads
GH_TOKEN / GITHUB_TOKEN from the environment, so this works unattended (e.g. in
a CI or remote-agent environment) as long as a token is present.

Exit codes:
    0  success
    1  fatal error (missing/unauthenticated gh, missing input files)
    2  partial run: one or more searches failed (e.g. rate limiting); the
       printed results may be incomplete

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
import time
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

# github.com paths that look like "owner/repo" but aren't repositories.
NON_REPO_OWNERS = {"topics", "sponsors", "marketplace", "features", "about",
                   "settings", "orgs", "users", "search"}

# JSON fields requested from `gh search repos`. `pushedAt` reflects real code
# activity (last push), unlike `updatedAt` which also moves on metadata changes
# such as a new star or an edited description.
GH_FIELDS = "fullName,description,stargazersCount,pushedAt,updatedAt,language,url,isArchived,isFork"

# GitHub's authenticated search API allows ~30 requests/minute; pause between
# queries so a full keyword sweep stays comfortably under that ceiling.
DEFAULT_SLEEP = 2.5


def load_keywords(path: Path) -> list[str]:
    keywords: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keywords.append(line)
    return keywords


def normalize_repo(full_name: str) -> str:
    """Normalize an ``owner/repo`` string for set comparison."""
    name = full_name.strip().lower().rstrip("/").rstrip(".")
    if name.endswith(".git"):
        name = name[:-4]
    return name


def repos_in_text(text: str, plus_only: bool = False) -> set[str]:
    """Extract every ``owner/repo`` referenced by a github.com link in ``text``.

    When ``plus_only`` is set, only added lines of a unified diff (those that
    start with ``+`` but not ``+++``) are considered.
    """
    found: set[str] = set()
    for line in text.splitlines():
        if plus_only and not (line.startswith("+") and not line.startswith("+++")):
            continue
        for match in GH_LINK_RE.findall(line):
            repo = normalize_repo(match)
            owner, _, name = repo.partition("/")
            if owner in NON_REPO_OWNERS or not name:
                continue
            found.add(repo)
    return found


def ensure_gh_auth() -> None:
    """Exit with a clear message unless `gh` is installed and authenticated."""
    try:
        proc = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=20
        )
    except FileNotFoundError:
        sys.exit("error: the GitHub CLI (`gh`) is not installed or not on PATH.")
    except subprocess.TimeoutExpired:
        sys.exit("error: `gh auth status` timed out.")
    if proc.returncode != 0:
        sys.exit(
            "error: `gh` is not authenticated. Set GH_TOKEN/GITHUB_TOKEN in the "
            "environment or run `gh auth login`.\n" + proc.stderr.strip()
        )


def gh_search(query: str, limit: int, sort: str) -> tuple[list[dict], str | None]:
    """Run one `gh search repos` query.

    Returns ``(results, error)`` where ``error`` is ``None`` on success or a
    short message describing why the query produced no usable output.
    """
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
        return [], f"query timed out: {query!r}"
    except subprocess.CalledProcessError as exc:
        return [], f"query failed ({query!r}): {exc.stderr.strip()}"
    try:
        return json.loads(proc.stdout or "[]"), None
    except json.JSONDecodeError:
        return [], f"unparseable response for query {query!r}"


def open_pr_repos() -> set[str]:
    """``owner/repo`` links already proposed (added) in any open pull request.

    Scanning open PRs prevents re-suggesting a project whose adding PR has not
    been merged yet — without this, every run until merge would stack a
    duplicate PR for the same find.
    """
    try:
        listing = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--json", "number", "--limit", "100"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        prs = json.loads(listing.stdout or "[]")
    except (subprocess.SubprocessError, FileNotFoundError, json.JSONDecodeError):
        return set()

    found: set[str] = set()
    for pr in prs:
        number = pr.get("number")
        if number is None:
            continue
        try:
            diff = subprocess.run(
                ["gh", "pr", "diff", str(number)],
                capture_output=True, text=True, check=True, timeout=30,
            )
        except subprocess.SubprocessError:
            continue
        found |= repos_in_text(diff.stdout, plus_only=True)
    return found


def parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        # gh returns RFC3339 timestamps, e.g. "2025-12-10T08:30:00Z".
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def discover(args: argparse.Namespace) -> tuple[list[dict], list[str]]:
    keywords = load_keywords(args.keywords)
    already = repos_in_text(args.readme.read_text(encoding="utf-8"))
    if args.exclude_open_prs:
        already |= open_pr_repos()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * args.inactive_months)

    candidates: dict[str, dict] = {}
    errors: list[str] = []
    for i, query in enumerate(keywords):
        if not args.quiet:
            print(f"searching: {query}", file=sys.stderr)
        if i:
            time.sleep(args.sleep)  # stay under the search-API rate limit
        results, error = gh_search(query, args.limit, args.sort)
        if error:
            errors.append(error)
            print(f"  warning: {error}", file=sys.stderr)
            continue
        for repo in results:
            key = normalize_repo(repo.get("fullName", ""))
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
            pushed = parse_ts(repo.get("pushedAt") or repo.get("updatedAt") or "")
            if pushed and pushed < cutoff:
                continue
            repo["_matchedQuery"] = query
            candidates[key] = repo

    results = sorted(candidates.values(),
                     key=lambda r: r.get("stargazersCount") or 0, reverse=True)
    return results, errors


def render_markdown(results: list[dict], errors: list[str]) -> str:
    lines: list[str] = []
    if errors:
        lines += [
            f"> ⚠️ {len(errors)} search(es) failed (possible rate limiting); "
            "results may be incomplete.",
            "",
        ]
    if not results:
        lines.append("No new candidate projects found.")
        return "\n".join(lines)
    lines += [
        f"## Candidate Catholic projects ({len(results)} found)",
        "",
        "Review each below; check off the ones worth adding to the list.",
        "",
    ]
    for r in results:
        stars = r.get("stargazersCount") or 0
        lang = r.get("language") or "—"
        desc = (r.get("description") or "").strip() or "_(no description)_"
        pushed = (r.get("pushedAt") or r.get("updatedAt") or "")[:10]
        lines.append(
            f"- [ ] [{r['fullName']}]({r['url']}) — ⭐ {stars} · {lang} · "
            f"pushed {pushed} · matched `{r['_matchedQuery']}`\n"
            f"      {desc}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
                        help="drop repos not pushed within this many months (default: 24)")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP,
                        help=f"seconds to pause between searches (default: {DEFAULT_SLEEP})")
    parser.add_argument("--no-archived", action=argparse.BooleanOptionalAction,
                        default=True, help="exclude archived repos (default: on)")
    parser.add_argument("--no-forks", action=argparse.BooleanOptionalAction,
                        default=True, help="exclude forks (default: on)")
    parser.add_argument("--exclude-open-prs", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="also skip repos already proposed in open PRs (default: on)")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown",
                        help="output format (default: markdown)")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress progress output on stderr")
    args = parser.parse_args()

    if not args.readme.exists():
        sys.exit(f"error: README not found at {args.readme}")
    if not args.keywords.exists():
        sys.exit(f"error: keywords file not found at {args.keywords}")

    ensure_gh_auth()

    results, errors = discover(args)

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        print(render_markdown(results, errors))

    # Signal a degraded run so callers (e.g. the scheduled agent) don't mistake
    # a rate-limited sweep for "nothing new."
    if errors:
        print(f"warning: {len(errors)} search(es) failed; results may be "
              "incomplete.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
