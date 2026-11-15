# AGENTS.md

Instructions for AI coding agents (Claude Code, Codex, Cursor, Gemini CLI and others) helping a person use or
change this repository. People: see [README.md](README.md) / [README.ja.md](README.ja.md).

## What this is

`g2f.py` moves every GitHub repository of a user or org to Forgejo with issues and PRs, sorts them into Forgejo
orgs from a map file (`map.toml`), and protects default branches. One file, Python 3.11+, standard library only.

## Helping someone migrate

Work in this order and stop for the person's yes where marked.

1. **Tokens: never in the chat.** Ask the person to set `GITHUB_TOKEN` and `FORGEJO_TOKEN` in their own shell
   (`read -rs GITHUB_TOKEN && export GITHUB_TOKEN`). Do not ask them to paste a token to you, do not write tokens
   into files, commands you show, or the map.
2. **Plan.** Run `python3 g2f.py plan --github-owner <name> > map.toml`. Fill in `[forgejo] url` and
   `[protect] users` with values the person gives you.
3. **Propose the orgs.** Sort the names under `unsorted` into orgs. Use what you know about the person's projects
   from your own context (their notes, other repos, what they told you); that knowledge stays on their machine and
   this tool never needs it. Group by project or product, keep old or dead ones in an `archive` org, and show the
   person the proposed `[orgs]` table. **Wait for their yes or their edits.**
4. **Dry run.** `python3 g2f.py migrate --map map.toml --dry-run`. It must list every repo and report
   `0 failed`; if it stops with "in no org", put those names into an org and repeat.
5. **Migrate.** Only after the person says go: `python3 g2f.py migrate --map map.toml --log migrate.log`.
   It can take a while (about 12 s a repo on average, large ones much longer). It is safe to run again: repos that
   are already there are skipped. On a timeout, point the person to `[git.timeout] MIGRATE` in Forgejo's `app.ini`.
6. **Protect.** `protect --dry-run` first, show the result, then `protect` after the person's yes. If agents will
   develop in these repos, suggest `[teams]` so agent accounts can push branches and open PRs but never merge.
7. **Report** what was migrated, skipped and failed (from the log), and that nothing was deleted on GitHub.

Do not delete, archive or change anything on GitHub as part of this; that is the person's separate decision.

## Changing the code

- Keep it one file with no dependencies outside the standard library.
- Run `python3 -m pytest -q` before and after a change; add a test for every new behaviour. The tests use an
  in-memory fake of both APIs (`Fake` in `test_g2f.py`); no network.
- Every command must keep `--dry-run` writing nothing, and no token may ever reach stdout, stderr or the log
  (there is a test for this; extend it when you add output).
- Writes go through `Forgejo.send`, which is what makes `--dry-run` safe. Do not call `http` with a write method
  directly.
- Keep README.md and README.ja.md in step when behaviour or flags change.
