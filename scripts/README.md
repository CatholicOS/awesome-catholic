# Discovery tooling

Helpers for keeping the awesome-catholic list growing.

## `discover.py`

Searches GitHub for Catholic projects, removes anything already linked from the
top-level `README.md`, applies quality filters, and prints the remaining
candidates for review.

### Requirements

- Python 3.10+ (standard library only — no third-party packages, no `gh` CLI).
- A GitHub token in `GH_TOKEN` or `GITHUB_TOKEN`. Any token works for searching
  public repos; the unauthenticated search API is too rate-limited (10 req/min)
  to use. Locally you can do `export GH_TOKEN=$(gh auth token)` if you have the
  CLI, or use a fine-grained PAT.

### Usage

```bash
# Markdown review list with default filters (>=2 stars, active in last 24 mo)
./scripts/discover.py

# Stricter: only well-established repos
./scripts/discover.py --min-stars 10

# Machine-readable output (used by the scheduled agent)
./scripts/discover.py --format json

# Widen the activity window and include archived repos
./scripts/discover.py --inactive-months 48 --no-no-archived
```

Run `./scripts/discover.py --help` for the full set of options.

### Authentication

The script calls the GitHub REST API directly and reads its token from
`GH_TOKEN` / `GITHUB_TOKEN`, so it runs unattended (CI, remote agents) wherever
a token is present — no `gh` CLI required. It preflight-checks the token
(`GET /rate_limit`) and exits with a clear message if it's missing or rejected.

### Dedup & exit codes

Candidates already linked from `README.md` are skipped, and so are repos already
proposed in any **open pull request** — so back-to-back runs won't stack
duplicate PRs for the same find before the first one merges.

Exit `0` is a clean run; `2` means some searches failed (e.g. rate limiting) and
the output is incomplete; `1` is a fatal error (missing/unauthenticated `gh` or
missing input files).

### Tuning the search

Edit [`keywords.txt`](keywords.txt) to add or refine search terms. Each non-blank,
non-comment line is one GitHub repo-search query, so search qualifiers
(`topic:catholic`, `in:name,description`, etc.) work. Keep the list multilingual —
many Catholic projects come from Italian, Spanish, Portuguese and French authors.

### Expect false positives

Keyword search is broad on purpose: "rosary" also matches some non-Catholic apps,
and project names occasionally collide (e.g. a security tool named "RosaryAV").
The output is a *candidate* list for a human (or the review agent) to judge — it
is not meant to be added verbatim.

## `audit.py`

Keeps the list current by moving entries between the active sections and the
**Attic** based on each backing repo's last push date (same token/auth as
`discover.py`).

```bash
./scripts/audit.py             # report proposed moves (no changes)
./scripts/audit.py --apply     # perform the repo moves in README.md
./scripts/audit.py --months 24 --revive-months 6   # tune the thresholds
```

- **Stale → Attic**: active-section repos archived or not pushed in `--months`
  months (default 36).
- **Attic → origin**: attic'd repos pushed within `--revive-months` months
  (default 12). The gap between the two windows is **hysteresis** — it stops
  entries near the threshold from flapping in and out each run.
- Attic moves record an `<!-- origin: <Section> -->` marker so revival is
  deterministic. Websites/apps are neither moved nor liveness-checked —
  reachability from the run environment is unreliable (sandboxed DNS can make a
  live site look dead), so they're only counted and curated by hand.

## Scheduled agents

Two scheduled Claude Code agents run against this repo, each opening a PR you
review:

- **Discovery** (weekly) runs `discover.py`, vets candidates, and adds new
  Catholic projects — see [`AGENT_PROMPT.md`](AGENT_PROMPT.md).
- **Maintenance** (monthly) runs `audit.py --apply` and proposes stale↔Attic
  moves — see [`MAINTENANCE_PROMPT.md`](MAINTENANCE_PROMPT.md).
