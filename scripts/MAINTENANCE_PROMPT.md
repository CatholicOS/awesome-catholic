# Scheduled maintenance agent — instructions

You keep the **awesome-catholic** list (`CatholicOS/awesome-catholic`) current by
moving entries between the active sections and the **Attic** as projects go
dormant or come back to life. You only ever *move* existing entries — you do not
add or remove any. Work conservatively and open at most one PR.

## Steps

1. **Sync.** `git checkout main && git pull --ff-only`.

2. **Audit.** Run the report first:
   ```bash
   ./scripts/audit.py
   ```
   It proposes two kinds of move, decided by the backing repo's last push date:
   - **Stale → Attic**: active-section repos archived or not pushed in 36+ months.
   - **Attic → origin**: attic'd repos pushed within the last 12 months
     (genuine revival). The hysteresis gap between those windows is deliberate —
     do not narrow it, or borderline entries will flap each run.

   Exit code `2` means some repo checks failed (rate limit / network); note that
   the run is partial and consider skipping rather than acting on incomplete data.

3. **Apply moves (if any).**
   ```bash
   ./scripts/audit.py --apply
   ```
   - Stale → Attic moves append an `<!-- origin: <Section> -->` marker so the
     entry can later be revived to the right place. Revivals strip that marker
     and restore the entry to its origin section.
   - **Use judgment.** If a stale entry is a canonical reference that belongs in
     the main list despite inactivity, revert that one move by hand. If a revived
     entry's recorded origin section no longer fits, place it in the better one.
   - **Websites/apps are never auto-moved or auto-checked.** Link reachability
     from this environment is unreliable (sandboxed DNS/network — a live site can
     look dead), so it must not drive any move. The report only *counts* them;
     leave site curation to humans.

4. **Re-sort by stars** (always, even when there were no Attic moves — this is
   how the ordering stays fresh as star counts change):
   ```bash
   ./scripts/sort.py
   git diff
   ```
   It re-orders each section by current star count (descending; non-repo
   entries after) and badges any repo still missing a star badge.

5. **If `git diff` is empty, stop** — nothing moved and the order didn't change,
   so don't open a PR. Otherwise **open one PR** from a `maintenance/YYYY-MM-DD`
   branch. The body must list each Attic move with its direction, the entry name,
   its last-activity date, and the origin/destination section; note that the rest
   of the diff is the routine star re-sort. Also mention anything `audit.py`
   flagged for manual review (e.g. an attic repo missing its `origin` tag), if
   any. Keep changes to `README.md` only.

## Guardrails

- Move only — never add, remove, or reword entries; never touch anything but
  `README.md`.
- Never force-push, never commit to `main`, never merge the PR yourself.
- One PR per run. If an open `maintenance/*` PR already exists, stop.
- End the commit message with the `Co-Authored-By` line for Claude, and the PR
  body with the Claude Code generation line.
