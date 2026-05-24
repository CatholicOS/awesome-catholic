#!/usr/bin/env python3
"""Discover candidate Catholic projects on GitHub for the awesome-catholic list.

Runs a set of GitHub searches (see ``keywords.txt``), drops anything already
linked from ``README.md`` *or* already proposed in an open pull request,
applies basic quality filters (stars, recency, archived/fork status), and
prints the remaining candidates as a Markdown review list or as JSON.

Talks to the GitHub REST API directly (no `gh` CLI dependency), so it runs
anywhere Python does — locally or in a sandboxed agent environment. It reads a
token from ``GH_TOKEN`` or ``GITHUB_TOKEN``; authentication is required because
the unauthenticated search API is rate-limited to 10 requests/minute.

Exit codes:
    0  success
    1  fatal error (no/invalid token, missing input files)
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
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_README = REPO_ROOT / "README.md"
DEFAULT_KEYWORDS = Path(__file__).resolve().parent / "keywords.txt"

API_ROOT = "https://api.github.com"

# Matches the owner/repo of any github.com link, ignoring the scheme and any
# trailing path, query string, ".git" suffix or punctuation.
GH_LINK_RE = re.compile(
    r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.IGNORECASE
)

# github.com paths that look like "owner/repo" but aren't repositories.
NON_REPO_OWNERS = {"topics", "sponsors", "marketplace", "features", "about",
                   "settings", "orgs", "users", "search"}

# GitHub's authenticated search API allows ~30 requests/minute; pause between
# queries so a full keyword sweep stays comfortably under that ceiling.
DEFAULT_SLEEP = 2.5

# REST `sort` values differ slightly from the gh CLI's; "best-match" means
# "omit the sort parameter".
SORT_PARAM = {"stars": "stars", "forks": "forks", "updated": "updated",
              "best-match": ""}


def token() -> str | None:
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


def api_get(path: str, params: dict | None = None,
            accept: str = "application/vnd.github+json") -> object:
    """GET a GitHub REST endpoint and return the parsed JSON.

    Raises urllib.error.HTTPError / URLError on failure.
    """
    url = API_ROOT + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("Accept", accept)
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "awesome-catholic-discover")
    tok = token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


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


def ensure_auth() -> None:
    """Exit unless a usable GitHub token is present."""
    if not token():
        sys.exit(
            "error: no GitHub token found. Set GH_TOKEN or GITHUB_TOKEN — the "
            "REST search API requires authentication."
        )
    try:
        api_get("/rate_limit")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            sys.exit("error: GitHub token was rejected (HTTP "
                     f"{exc.code}). Check GH_TOKEN/GITHUB_TOKEN.")
    except urllib.error.URLError:
        pass  # transient network issue; let the real queries surface it


def normalize_item(item: dict) -> dict:
    """Map a REST search-result item to the stable shape the rest of the
    script (and the JSON consumed by the agent) expects."""
    return {
        "fullName": item.get("full_name", ""),
        "description": item.get("description"),
        "stargazersCount": item.get("stargazers_count", 0),
        "pushedAt": item.get("pushed_at", ""),
        "updatedAt": item.get("updated_at", ""),
        "language": item.get("language"),
        "url": item.get("html_url", ""),
        "isArchived": item.get("archived", False),
        "isFork": item.get("fork", False),
    }


def search_repos(query: str, limit: int, sort: str) -> tuple[list[dict], str | None]:
    """Run one repository search.

    Returns ``(results, error)`` where ``error`` is ``None`` on success or a
    short message describing why the query produced no usable output.
    """
    params = {"q": query, "order": "desc", "per_page": str(min(limit, 100))}
    sort_value = SORT_PARAM.get(sort, "stars")
    if sort_value:
        params["sort"] = sort_value
    try:
        data = api_get("/search/repositories", params)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("message", "")
        except Exception:
            pass
        return [], f"query failed ({query!r}): HTTP {exc.code} {detail}".strip()
    except urllib.error.URLError as exc:
        return [], f"query failed ({query!r}): {exc.reason}"
    except (TimeoutError, json.JSONDecodeError) as exc:
        return [], f"query failed ({query!r}): {exc}"
    items = data.get("items", []) if isinstance(data, dict) else []
    return [normalize_item(it) for it in items], None


def detect_repo() -> str | None:
    """Best-effort ``owner/repo`` for the current checkout."""
    env = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in env:
        return env.strip()
    try:
        url = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, check=True, timeout=15,
        ).stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    return match.group(1) if match else None


def open_pr_repos(repo: str | None) -> set[str]:
    """``owner/repo`` links already proposed (added) in any open pull request.

    Scanning open PRs prevents re-suggesting a project whose adding PR has not
    been merged yet — without this, every run until merge would stack a
    duplicate PR for the same find.
    """
    if not repo:
        return set()
    try:
        pulls = api_get(f"/repos/{repo}/pulls", {"state": "open", "per_page": "100"})
    except (urllib.error.URLError, json.JSONDecodeError):
        return set()
    if not isinstance(pulls, list):
        return set()

    found: set[str] = set()
    for pr in pulls:
        number = pr.get("number")
        if number is None:
            continue
        try:
            files = api_get(f"/repos/{repo}/pulls/{number}/files", {"per_page": "100"})
        except (urllib.error.URLError, json.JSONDecodeError):
            continue
        if not isinstance(files, list):
            continue
        for f in files:
            found |= repos_in_text(f.get("patch") or "", plus_only=True)
    return found


def parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        # GitHub returns RFC3339 timestamps, e.g. "2025-12-10T08:30:00Z".
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def discover(args: argparse.Namespace) -> tuple[list[dict], list[str]]:
    keywords = load_keywords(args.keywords)
    already = repos_in_text(args.readme.read_text(encoding="utf-8"))
    if args.exclude_open_prs:
        already |= open_pr_repos(detect_repo())
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * args.inactive_months)

    candidates: dict[str, dict] = {}
    errors: list[str] = []
    for i, query in enumerate(keywords):
        if not args.quiet:
            print(f"searching: {query}", file=sys.stderr)
        if i:
            time.sleep(args.sleep)  # stay under the search-API rate limit
        results, error = search_repos(query, args.limit, args.sort)
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
                        help="max results per query, 1-100 (default: 40)")
    parser.add_argument("--sort", choices=list(SORT_PARAM), default="stars",
                        help="how results are ranked per query (default: stars)")
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

    ensure_auth()

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
