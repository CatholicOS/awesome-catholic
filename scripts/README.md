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
non-comment line is one `gh search repos` query, so GitHub search qualifiers
(`topic:catholic`, `in:name,description`, etc.) work. Keep the list multilingual —
many Catholic projects come from Italian, Spanish, Portuguese and French authors.

### Expect false positives

Keyword search is broad on purpose: "rosary" also matches some non-Catholic apps,
and project names occasionally collide (e.g. a security tool named "RosaryAV").
The output is a *candidate* list for a human (or the review agent) to judge — it
is not meant to be added verbatim.

## Scheduled discovery agent

A scheduled Claude Code agent runs `discover.py`, reviews the candidates, and
opens a pull request adding the worthwhile ones to `README.md`. See
[`AGENT_PROMPT.md`](AGENT_PROMPT.md) for the exact instructions it follows.
