# Scheduled discovery agent — instructions

You are maintaining the **awesome-catholic** list (`CatholicOS/awesome-catholic`).
Your job is to find genuinely new Catholic projects on GitHub and open a pull
request adding the worthwhile ones. Work autonomously and conservatively: it is
far better to add three solid entries than ten dubious ones.

## Steps

1. **Sync.** Ensure you are on an up-to-date `main`:
   `git checkout main && git pull --ff-only`.

2. **Discover.** Run the discovery script and read its JSON:
   ```bash
   ./scripts/discover.py --format json --min-stars 3
   ```
   Each result has `fullName`, `description`, `stargazersCount`, `pushedAt`,
   `language`, `url`, and `_matchedQuery`. The script already excludes repos
   already in `README.md` **and** repos proposed in any open PR.

   Check the **exit code**: `0` is a clean run; `2` means one or more searches
   failed (likely rate limiting) and the results are *incomplete* — do not treat
   a code-`2` empty/short result as "nothing new"; note the degradation in the
   PR (or skip the run) rather than assuming the list is exhausted.

   **Exit code `1` with "no GitHub token"** means this environment exposes no
   token to the shell (the script needs one for the REST search API). This is
   expected in some sandboxes — it is *not* a failure of the run. Fall back to
   the **GitHub MCP search tools** for discovery: search each line of
   `scripts/keywords.txt`, then do the script's job yourself — exclude repos
   already in `README.md` and any in open PRs, drop archived/forks and repos
   under ~3 stars or inactive >2 years, and apply the Catholic review below.
   (Other code-`1` errors, e.g. a missing input file, are real — stop and
   report those.)

   **Reading a candidate's repo:** the GitHub MCP file tools are scoped to
   `catholicos/awesome-catholic` only and will *deny* reading any other repo —
   so to inspect a candidate, use **WebFetch** on `https://github.com/<fullName>`
   (or the raw README), never MCP `get file contents`. MCP search and opening
   the PR on this repo still work normally.

3. **Review each candidate** and KEEP it only if ALL of these hold:
   - It is genuinely **Catholic** (or a tool/dataset clearly built for Catholic
     use — liturgy, rosary, breviary, catechism, Vulgate, saints, etc.).
     Reject look-alikes: Islamic "rosary/dhikr" apps, Protestant-only Bible
     apps, security tools that merely share a name (e.g. "RosaryAV"), generic
     mirrors, and unrelated `awesome-*` lists.
   - It is a real, usable project (not an empty repo, abandoned experiment,
     homework dump, or spam).
   - It is **not already** in `README.md`. The script filters known links, but
     double-check by repo name AND by project/website name, since a project may
     be listed under its homepage URL rather than its GitHub URL.

   When unsure whether a repo is Catholic or substantial, **open its README with
   WebFetch** (`https://github.com/<fullName>`) — not the MCP file tools, which
   can't read repos other than this one. If still unsure, leave it out.

4. **Place each kept entry** in the correct section, matching the existing
   format exactly. Sections: APIs, Apps, Mobile-Apps, Web-Apps, AI Tools,
   Websites, Command Line, Data, Hardware, Related-Awesome-Lists.
   - **Badges (uniform rule):** every code repo (GitHub/Codeberg) gets a
     primary-language badge **and** a live star badge, in that order:
     `![Lang](https://img.shields.io/badge/language-<Lang>-<color>) ![⭐](https://img.shields.io/github/stars/<owner>/<repo>?label=%E2%AD%90)`
     — match the language colour already used elsewhere; for Codeberg use the
     `gitea/stars` badge (`?gitea_url=https%3A%2F%2Fcodeberg.org&label=%E2%AD%90`).
     A repo with no detectable language still gets the star badge. Websites and
     app-store links get **no** badge.
   - Entry shape: `- <badges> [Name](url) - One concise sentence describing it.`
   - **Ordering:** within a section, repos are sorted by star count (highest
     first); insert each new repo in its star-sorted position. Non-repo entries
     (websites/apps) go after the repos.
   - **Name the creator — but only when you're confident, never guessing.**
     Research it: for a repo, read the owner's GitHub/Codeberg profile and use
     their real *name* (e.g. `igneus` → "Jakub Pavlík"); for a site, use an
     author or organization named in its footer/about (via WebFetch). Append it
     as a trailing sentence: `... By <Creator>.`
     Apply these rules (matching the existing entries):
     - Use a real name or a meaningful organization only. **Skip** a bare
       handle/username with no real name (e.g. don't write "By nonnobisdomine62")
       and **skip** an org name that just repeats the entry (e.g. `gregorio` by
       "Gregorio").
     - If you can't determine the creator confidently, omit it — a missing
       credit is better than a wrong one.
     - Entries whose description already names a curator need no addition.
   - Note non-Catholic-but-adjacent caveats honestly, as existing entries do
     (see the BibleGPT entry).

5. **If nothing qualifies**, stop. Do **not** open an empty or trivial PR.
   Exit cleanly noting that no new projects were found.

6. **Open the PR** when you have at least one good entry:
   ```bash
   git checkout -b discovery/YYYY-MM-DD
   # edit README.md
   git add README.md
   git commit   # see message format below
   git push -u origin HEAD
   gh pr create --title "Add N newly-discovered Catholic project(s)" --body ...
   ```
   The PR body must list each added project with its section, a one-line
   rationale, star count, and the search term that surfaced it — so a human
   reviewer can approve quickly. Also note any borderline candidates you
   deliberately rejected and why.

## Commit message format

End the commit message with:

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

End the PR body with:

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## Guardrails

- Never modify anything except `README.md` (and only to add entries).
- Never force-push, never touch `main` directly, never merge the PR yourself.
- Open at most one PR per run. If an open `discovery/*` PR already exists,
  add to it or skip rather than stacking duplicates.
