# Discovery tooling

Helpers for keeping the awesome-catholic list growing.

## `discover.py`

Searches GitHub for Catholic projects, removes anything already linked from the
top-level `README.md`, applies quality filters, and prints the remaining
candidates for review.

### Requirements

- [GitHub CLI](https://cli.github.com/) (`gh`) installed and authenticated
  (`gh auth status` should show you logged in).
- Python 3.10+.

### Usage

```bash
# Markdown review list with default filters (>=2 stars, active in last 24 mo)
./scripts/discover.py

# Stricter: only well-established repos
./scripts/discover.py --min-stars 10

# Machine-readable output (used by the scheduled agent)
./scripts/discover.py --format json

# Widen the activity window and include archived repos
./scripts/discover.py --inactive-months 48 --include-archived
```

Run `./scripts/discover.py --help` for the full set of options.

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
