import io
import json
import tomllib
from contextlib import redirect_stdout

import pytest

import g2f

REPOS = [
    {"name": "tool-a", "private": False, "language": "Python", "description": "a tool", "fork": False, "owner": {"login": "me"}},
    {"name": "old", "private": True, "language": None, "description": None, "fork": False, "owner": {"login": "me"}},
    {"name": "someone-elses", "private": False, "language": "Go", "description": "", "fork": True, "owner": {"login": "me"}},
]

MAP = """
[forgejo]
url = "https://forgejo.example.com"
[github]
owner = "me"
[defaults]
private = true
archive_orgs = ["archive"]
[protect]
users = ["me"]
protected_files = "acceptance/**"
[teams.developers]
permission = "write"
members = ["agent-a"]
[orgs]
tools = ["tool-a"]
archive = ["old"]
"""


class Fake:
    """GitHub + Forgejo in memory. Records every write."""
    def __init__(self, forgejo_repos=()):
        self.writes = []
        self.fj = set(forgejo_repos)
        self.orgs = set()

    def __call__(self, method, url, token, body=None, auth="token", timeout=120):
        if url.startswith(g2f.GITHUB_API):
            if url.endswith("/users/me"):
                return 200, {"type": "User"}
            return 200, REPOS
        path = url.split("/api/v1", 1)[1]
        if method == "GET":
            if path.startswith("/orgs/") and path.count("/") == 2:
                if path.split("/")[2] in self.orgs:
                    return 200, {}
                raise g2f.ApiError(404, "no")
            if path.startswith("/repos/"):
                full = "/".join(path.split("/")[2:4]).split("?")[0]
                if full in self.fj and path.count("/") == 3:
                    return 200, {"full_name": full, "archived": False, "default_branch": "main"}
                raise g2f.ApiError(404, "no")
            if path.endswith("/teams"):
                return 200, []
            if "/repos?" in path:
                org = path.split("/")[2]
                return 200, [{"full_name": f, "default_branch": "main"} for f in self.fj if f.startswith(org + "/")]
            raise g2f.ApiError(404, "no")
        self.writes.append((method, path, body))
        if path == "/orgs":
            self.orgs.add(body["username"])
        if path == "/repos/migrate":
            self.fj.add(f"{body['repo_owner']}/{body['repo_name']}")
        if path.endswith("/teams"):
            return 201, {"id": 7}
        return 201, {}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret_value")
    monkeypatch.setenv("FORGEJO_TOKEN", "fj_secret_value")
    p = tmp_path / "map.toml"
    p.write_text(MAP)
    return p


def test_map_rejects_a_repo_in_two_orgs(tmp_path):
    p = tmp_path / "m.toml"
    p.write_text('[orgs]\na = ["x"]\nb = ["x"]\n')
    with pytest.raises(SystemExit, match="both"):
        g2f.load_map(p)


def test_plan_prints_valid_toml_without_forks(env, monkeypatch):
    monkeypatch.setattr(g2f, "http", Fake())
    out = io.StringIO()
    with redirect_stdout(out):
        g2f.main(["plan", "--github-owner", "me"])
    m = tomllib.loads(out.getvalue())
    assert m["orgs"]["unsorted"] == ["old", "tool-a"]


def test_migrate_dry_run_writes_nothing(env, monkeypatch):
    fake = Fake()
    monkeypatch.setattr(g2f, "http", fake)
    out = io.StringIO()
    with redirect_stdout(out):
        g2f.main(["migrate", "--map", str(env), "--dry-run"])
    assert fake.writes == []
    assert "would    me/tool-a -> tools/tool-a" in out.getvalue()


def test_migrate_creates_orgs_migrates_and_archives_without_leaking_tokens(env, monkeypatch, tmp_path):
    fake = Fake()
    monkeypatch.setattr(g2f, "http", fake)
    log = tmp_path / "run.log"
    out = io.StringIO()
    with redirect_stdout(out):
        g2f.main(["migrate", "--map", str(env), "--log", str(log)])
    migrated = [b for m, p, b in fake.writes if p == "/repos/migrate"]
    assert {(b["repo_owner"], b["repo_name"]) for b in migrated} == {("tools", "tool-a"), ("archive", "old")}
    assert all(b["issues"] and b["pull_requests"] and b["private"] for b in migrated)
    assert ("PATCH", "/repos/archive/old", {"archived": True}) in fake.writes
    for text in (out.getvalue(), log.read_text()):
        assert "secret_value" not in text


def test_migrate_stops_when_a_repo_is_not_in_the_map(env, monkeypatch):
    monkeypatch.setattr(g2f, "http", Fake())
    env.write_text(MAP.replace('archive = ["old"]', "archive = []"))
    with pytest.raises(SystemExit, match="old"):
        g2f.main(["migrate", "--map", str(env)])


def test_migrate_skips_repos_already_there(env, monkeypatch):
    fake = Fake(forgejo_repos={"tools/tool-a"})
    monkeypatch.setattr(g2f, "http", fake)
    with redirect_stdout(io.StringIO()):
        g2f.main(["migrate", "--map", str(env)])
    assert [b["repo_name"] for m, p, b in fake.writes if p == "/repos/migrate"] == ["old"]


def test_protect_limits_push_and_merge_and_skips_archive(env, monkeypatch):
    fake = Fake(forgejo_repos={"tools/tool-a", "archive/old"})
    fake.orgs |= {"tools", "archive"}
    monkeypatch.setattr(g2f, "http", fake)
    with redirect_stdout(io.StringIO()):
        g2f.main(["protect", "--map", str(env)])
    rules = [(p, b) for m, p, b in fake.writes if p.endswith("/branch_protections")]
    assert [p for p, b in rules] == ["/repos/tools/tool-a/branch_protections"]
    b = rules[0][1]
    assert b["merge_whitelist_usernames"] == ["me"] and b["push_whitelist_usernames"] == ["me"]
    assert b["protected_file_patterns"] == "acceptance/**"
    assert ("PUT", "/teams/7/members/agent-a", None) in fake.writes


def test_protect_refuses_the_placeholder_user(env, monkeypatch):
    monkeypatch.setattr(g2f, "http", Fake())
    env.write_text(MAP.replace('users = ["me"]', 'users = ["CHANGE-ME"]'))
    with pytest.raises(SystemExit, match="protect"):
        g2f.main(["protect", "--map", str(env)])
