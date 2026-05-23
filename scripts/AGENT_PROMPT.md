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
   PR (or skip the run) rather than assuming the list is exhausted. `1` is a
   fatal error (e.g. `gh` not authenticated) — stop and report it.

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

   When unsure whether a repo is Catholic or substantial, **open its README**
   (fetch `https://github.com/<fullName>` or use the GitHub MCP tools) before
   deciding. If still unsure, leave it out.

4. **Place each kept entry** in the correct section, matching the existing
   format exactly. Sections: APIs, Apps, Mobile-Apps, Web-Apps, AI Tools,
   Websites, Command Line, Data, Hardware, Neovim, Related-Awesome-Lists.
   - Add a language badge when the section's entries use one, e.g.
     `![Python](https://img.shields.io/badge/language-Python-blue)`. Match the
     color convention already used for that language elsewhere in the file.
   - Entry shape: `- [Name](url) - One concise sentence describing it.`
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
