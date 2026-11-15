# github-to-forgejo

Move **every** repository of a GitHub user or org to [Forgejo](https://forgejo.org) in one run — with issues,
pull requests, labels, milestones, releases and wikis — sorted into Forgejo organizations, with the default branch
of each one protected.

Measured on one run: **132 repositories in 26 minutes**, issues and PRs included, on a home server.
One Python file, standard library only.

Forgejo's own migration screen moves one repository at a time. This tool does all of them from a single map file
you can read, edit and keep.

```
g2f.py plan --github-owner you > map.toml   # 1. list your repos as a draft map
$EDITOR map.toml                            # 2. sort them into orgs (or let your own agent do it, see below)
g2f.py migrate  --map map.toml --dry-run    # 3. see what would happen
g2f.py migrate  --map map.toml              # 4. migrate
g2f.py protect  --map map.toml              # 5. protect default branches, optional role teams
```

## Requirements

- Python 3.11 or newer
- A Forgejo you can reach, and a token of an admin there (or an owner of the target orgs): `FORGEJO_TOKEN`
- A GitHub token that can read the repos: `GITHUB_TOKEN`. A fine-grained token with **All repositories** and
  read access to Contents, Issues, Pull requests and Metadata is enough.

Tokens are read from the environment only. They are never printed, logged or written to the map.

```sh
read -rs GITHUB_TOKEN && export GITHUB_TOKEN     # paste, Enter (nothing is shown)
read -rs FORGEJO_TOKEN && export FORGEJO_TOKEN
```

## The map

`plan` writes a draft with every repository under `unsorted`, one line each with its visibility, language and
description as a comment. Move the names into the orgs you want:

```toml
[forgejo]
url = "https://forgejo.example.com"

[github]
owner = "you"

[defaults]
private = true                 # migrated repos are private on Forgejo
archive_orgs = ["archive"]     # repos in these orgs become read-only

[protect]
users = ["you"]                # only these may push to or merge into the default branch
protected_files = "acceptance/**;.forgejo/workflows/**"   # optional

[teams.developers]             # optional: a role team in every org
permission = "write"
members = ["bot-a", "bot-b"]

[teams.reviewers]
permission = "read"
members = ["reviewer-bot"]

[orgs]
tools   = ["cli-thing", "dotfiles"]
web     = ["site", "blog"]
archive = ["old-experiment"]
```

Every GitHub repository has to be under exactly one org; `migrate` stops and names the ones you forgot. The map is
also the record of where everything went.

### Let your own agent sort it

The map is plain text, so you can hand the `plan` output to a local AI agent you trust, together with what it
knows about your projects, and ask it to propose the orgs. Your project details never have to leave your machine,
and this tool needs none of them: it only reads the finished map.

## Commands

| command | what it does |
|---|---|
| `plan --github-owner NAME` | prints a draft map of the repos the token can see (forks left out) |
| `migrate --map M` | creates the orgs, migrates each repo straight into its org, archives the archive orgs. Repos already on Forgejo are skipped, so it can be run again after a failure |
| `organize --map M --from-owner USER` | for repos you already migrated under a user: moves them into their orgs |
| `protect --map M` | protects each default branch (push and merge only for `[protect] users`), creates the `[teams]` in every org |

All of them take `--dry-run` (nothing is written) and `--log FILE`.

## Notes

- Large repositories can take longer than Forgejo's default git timeouts. If a migration fails with a timeout,
  raise `[git.timeout] MIGRATE` in Forgejo's `app.ini` (for example 3600) and run `migrate` again.
- Pull requests from forks come over as read-only history: their branches live in the fork, not in your repo.
- Bot PRs (Dependabot and the like) come over too, but the bot keeps working on GitHub only.
- Issue and PR numbers stay the same, so `owner/repo#123` keeps pointing at the same thing.
- Nothing is deleted on GitHub. What to do with the GitHub side (keep as a public mirror, archive, close PRs) is up
  to you.

## Why protect and role teams

The setup this came from lets local AI agents develop in the migrated repositories: they push branches and open
PRs, a separate account reviews, and only people merge. The role teams (`developers` write, `reviewers` read) and
the merge restriction in `protect` are what make that safe to leave running. If you migrate for people only, use
`protect` with your own name and skip `[teams]`.

## Tests

```sh
python3 -m pytest -q
```

The tests run against an in-memory GitHub and Forgejo, and also check that no token ever reaches the output or the log.

## License

MIT. Maintenance is minimal: issues are read, fixes are not promised.

---

### 日本語

GitHub のユーザーまたは組織の全リポジトリを、Issue・PR・ラベル・マイルストーン・リリース・Wiki ごと Forgejo
へ一度に移し、組織に振り分け、既定ブランチを保護します。実測で 132 リポジトリを 26 分。Python 1 ファイル、
標準ライブラリだけ。振り分けの表（map.toml）は `plan` で下書きを作り、自分で、または手元のエージェントに
自分のプロジェクトの事情を渡して決めさせられます。このツールは出来上がった表しか読みません。
