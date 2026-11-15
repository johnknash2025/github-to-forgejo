#!/usr/bin/env python3
"""github-to-forgejo (g2f): move every repository of a GitHub user or org to Forgejo, with issues, pull requests,
labels, milestones, releases and wikis, then sort them into Forgejo organizations and protect their default branch.

    g2f.py plan     --github-owner NAME  > map.toml     list your GitHub repos as a draft map to edit
    g2f.py migrate  --map map.toml [--dry-run]           migrate every repo straight into its org
    g2f.py organize --map map.toml [--dry-run]           move already-migrated repos into their orgs, archive some
    g2f.py protect  --map map.toml [--dry-run]           protect default branches (push/merge only for listed users)

Tokens come from the environment only, and are never printed or logged:
    GITHUB_TOKEN   read-only token that can see the repos (fine-grained: "All repositories", Contents/Issues/
                   Pull requests/Metadata read)
    FORGEJO_TOKEN  a Forgejo token of an admin (or an owner of the target orgs)
Standard library only. Python 3.11+.
"""
import argparse
import json
import os
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

GITHUB_API = "https://api.github.com"
UNITS = ["repo.code", "repo.issues", "repo.pulls", "repo.wiki", "repo.releases", "repo.actions"]


class ApiError(RuntimeError):
    def __init__(self, code, text):
        super().__init__(f"HTTP {code}: {text[:300]}")
        self.code = code


def http(method, url, token, body=None, auth="token", timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, data=data, headers={
        "Authorization": f"{auth} {token}", "Content-Type": "application/json", "Accept": "application/json",
        "User-Agent": "github-to-forgejo"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raise ApiError(e.code, e.read().decode("utf-8", "replace")) from None
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


class Forgejo:
    def __init__(self, url, token, dry=False):
        self.api = url.rstrip("/") + "/api/v1"
        self.token, self.dry = token, dry

    def get(self, path):
        try:
            return http("GET", self.api + path, self.token)[1]
        except ApiError as e:
            if e.code == 404:
                return None
            raise

    def send(self, method, path, body=None, timeout=120):
        if self.dry:
            return None
        return http(method, self.api + path, self.token, body, timeout=timeout)[1]

    def pages(self, path):
        out, page = [], 1
        sep = "&" if "?" in path else "?"
        while True:
            got = self.get(f"{path}{sep}limit=50&page={page}") or []
            out += got
            if len(got) < 50:
                return out
            page += 1


# ---------------------------------------------------------------- the map

def load_map(path):
    """map.toml:
        [forgejo]
        url = "https://forgejo.example.com"
        [github]
        owner = "your-github-name"         # user or org
        [defaults]
        private = true                     # migrated repos are private on Forgejo
        archive_orgs = ["archive"]         # repos in these orgs become read-only
        [protect]
        users = ["you"]                    # only these may push to / merge into the default branch
        protected_files = "acceptance/**;.forgejo/workflows/**"
        [teams.developers]                 # optional role teams, created in every org
        permission = "write"
        members = ["agent-a"]
        [orgs]
        tools = ["repo-a", "repo-b"]
        archive = ["old-thing"]
    Every GitHub repo name must appear under exactly one org.
    """
    with open(path, "rb") as f:
        m = tomllib.load(f)
    seen = {}
    for org, repos in m.get("orgs", {}).items():
        for r in repos:
            if r in seen:
                raise SystemExit(f"map: {r} is under both {seen[r]} and {org}")
            seen[r] = org
    m["_where"] = seen
    return m


def github_repos(owner, token):
    """Every repo of a GitHub user or org that the token can see (forks left out)."""
    out, page = [], 1
    kind = "orgs" if http("GET", f"{GITHUB_API}/users/{owner}", token, auth="Bearer")[1].get("type") == "Organization" else "user"
    while True:
        path = (f"/orgs/{owner}/repos?type=all" if kind == "orgs" else "/user/repos?affiliation=owner")
        got = http("GET", f"{GITHUB_API}{path}&per_page=100&page={page}", token, auth="Bearer")[1]
        out += [r for r in got if not r.get("fork") and r["owner"]["login"].lower() == owner.lower()]
        if len(got) < 100:
            return out
        page += 1


def cmd_plan(a):
    tok = need("GITHUB_TOKEN")
    repos = github_repos(a.github_owner, tok)
    print(f'[forgejo]\nurl = "https://forgejo.example.com"\n\n[github]\nowner = "{a.github_owner}"\n\n'
          f'[defaults]\nprivate = true\narchive_orgs = ["archive"]\n\n[protect]\nusers = ["CHANGE-ME"]\n'
          f'protected_files = ""\n\n# Sort the repos below into orgs. Lines are "name  # private|public  language  description".\n'
          f"[orgs]\nunsorted = [")
    for r in sorted(repos, key=lambda r: r["name"].lower()):
        note = f'{"private" if r["private"] else "public"}  {r.get("language") or "-"}  {(r.get("description") or "")[:70]}'
        print(f'  "{r["name"]}",  # {note}')
    print("]")
    print(f"{len(repos)} repositories", file=sys.stderr)


def need(var):
    v = os.environ.get(var, "").strip()
    if not v:
        raise SystemExit(f"set {var} in the environment")
    return v


def ensure_org(fj, org, log):
    if fj.get(f"/orgs/{org}") is None:
        fj.send("POST", "/orgs", {"username": org, "visibility": "private"})
        log(f"org      {org}  created")


def cmd_migrate(a):
    m = load_map(a.map)
    gtok = need("GITHUB_TOKEN")
    fj = Forgejo(m["forgejo"]["url"], need("FORGEJO_TOKEN"), a.dry_run)
    owner = m["github"]["owner"]
    private = m.get("defaults", {}).get("private", True)
    log = logger(a)
    names = {r["name"] for r in github_repos(owner, gtok)}
    missing = sorted(names - set(m["_where"]))
    if missing:
        raise SystemExit("map: these GitHub repos are in no org: " + ", ".join(missing))
    for org in sorted(set(m["_where"].values())):
        ensure_org(fj, org, log)
    ok = skip = fail = 0
    todo = sorted(n for n in m["_where"] if n in names)
    for i, name in enumerate(todo, 1):
        org = m["_where"][name]
        tag = f"[{i}/{len(todo)}]"
        if fj.get(f"/repos/{org}/{name}") is not None:
            log(f"{tag} exists   {org}/{name}"); skip += 1; continue
        body = {"clone_addr": f"https://github.com/{owner}/{name}.git", "repo_owner": org, "repo_name": name,
                "service": "github", "auth_token": gtok, "mirror": False, "private": private, "issues": True,
                "pull_requests": True, "labels": True, "milestones": True, "releases": True, "wiki": True}
        if a.dry_run:
            log(f"{tag} would    {owner}/{name} -> {org}/{name}"); continue
        t0 = time.time()
        try:
            fj.send("POST", "/repos/migrate", body, timeout=3600)
            log(f"{tag} migrated {org}/{name}  {time.time() - t0:.0f}s"); ok += 1
        except Exception as e:
            log(f"{tag} FAILED   {org}/{name}: {e}"); fail += 1
    archive(fj, m, log)
    log(f"done: {ok} migrated, {skip} already there, {fail} failed")
    return 1 if fail else 0


def archive(fj, m, log):
    for org in m.get("defaults", {}).get("archive_orgs", []):
        for name in m.get("orgs", {}).get(org, []):
            r = fj.get(f"/repos/{org}/{name}")
            if r and not r.get("archived"):
                fj.send("PATCH", f"/repos/{org}/{name}", {"archived": True})
                log(f"archive  {org}/{name}")


def cmd_organize(a):
    """For repos migrated earlier under a user: move each into its org."""
    m = load_map(a.map)
    fj = Forgejo(m["forgejo"]["url"], need("FORGEJO_TOKEN"), a.dry_run)
    log = logger(a)
    for org in sorted(set(m["_where"].values())):
        ensure_org(fj, org, log)
    for name, org in sorted(m["_where"].items()):
        if fj.get(f"/repos/{org}/{name}") is not None:
            continue
        if fj.get(f"/repos/{a.from_owner}/{name}") is None:
            log(f"missing  {a.from_owner}/{name}"); continue
        fj.send("POST", f"/repos/{a.from_owner}/{name}/transfer", {"new_owner": org})
        log(f"move     {a.from_owner}/{name} -> {org}/{name}")
    archive(fj, m, log)


def cmd_protect(a):
    m = load_map(a.map)
    fj = Forgejo(m["forgejo"]["url"], need("FORGEJO_TOKEN"), a.dry_run)
    log = logger(a)
    p = m.get("protect", {})
    users = p.get("users") or []
    if not users or "CHANGE-ME" in users:
        raise SystemExit("map: set [protect] users")
    rule = {"enable_push": True, "enable_push_whitelist": True, "push_whitelist_usernames": users,
            "enable_merge_whitelist": True, "merge_whitelist_usernames": users,
            "protected_file_patterns": p.get("protected_files", ""), "dismiss_stale_approvals": True}
    skip_orgs = set(m.get("defaults", {}).get("archive_orgs", []))
    teams = m.get("teams", {})
    n = 0
    for org in sorted(set(m["_where"].values()) - skip_orgs):
        have = {t["name"]: t for t in (fj.get(f"/orgs/{org}/teams") or [])}
        for name, t in teams.items():
            perm = t.get("permission", "read")
            if name not in have:
                made = fj.send("POST", f"/orgs/{org}/teams", {"name": name, "permission": perm,
                               "includes_all_repositories": True, "units": UNITS, "units_map": {u: perm for u in UNITS}})
                have[name] = made or {"id": None}
                log(f"team     {org}/{name} ({perm})")
            for user in t.get("members", []):
                if have[name].get("id"):
                    fj.send("PUT", f"/teams/{have[name]['id']}/members/{user}")
        for r in fj.pages(f"/orgs/{org}/repos"):
            if r.get("empty") or r.get("archived"):
                continue
            br, full = r["default_branch"], r["full_name"]
            rules = fj.get(f"/repos/{full}/branch_protections") or []
            if any(x.get("rule_name") == br for x in rules):
                fj.send("PATCH", f"/repos/{full}/branch_protections/{br}", rule)
            else:
                fj.send("POST", f"/repos/{full}/branch_protections", {**rule, "rule_name": br})
            log(f"protect  {full}:{br}  push/merge: {', '.join(users)}")
            n += 1
    log(f"done: {n} branches")


def logger(a):
    f = open(a.log, "a") if getattr(a, "log", None) else None

    def log(s):
        line = ("(dry-run) " if a.dry_run else "") + s
        print(line, flush=True)
        if f:
            f.write(time.strftime("%F %T ") + line + "\n"); f.flush()
    return log


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="print a draft map of your GitHub repos")
    p.add_argument("--github-owner", required=True)
    for name, h in (("migrate", "migrate every repo into its org"), ("organize", "move migrated repos into orgs"),
                    ("protect", "protect default branches, create role teams")):
        s = sub.add_parser(name, help=h)
        s.add_argument("--map", required=True)
        s.add_argument("--dry-run", action="store_true")
        s.add_argument("--log", help="append a log here as well")
        if name == "organize":
            s.add_argument("--from-owner", required=True, help="the Forgejo user the repos are under now")
    a = ap.parse_args(argv)
    return {"plan": cmd_plan, "migrate": cmd_migrate, "organize": cmd_organize, "protect": cmd_protect}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
