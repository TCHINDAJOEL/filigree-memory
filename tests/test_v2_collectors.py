import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from filigree.collectors import all_collectors, discover_all, probe_all
from filigree.collectors.base import SessionInfo, to_iso
from filigree.collectors.claude_code import ClaudeCodeCollector
from filigree.collectors.claude_desktop import ClaudeDesktopCollector
from filigree.collectors.claude_tap import ClaudeTapCollector
from filigree.collectors.codex_rollout import CodexRolloutCollector
from filigree.collectors.codex_state import CodexStateCollector
from filigree.probe import run_probe
from filigree.resolver import proven_worktree_main, under_roots

SECRET = "SECRET-MESSAGE-TEXT-9f3a"


def write_jsonl(path: Path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / "home"
        self.home.mkdir()
        self.env = {}


class ClaudeCodeTests(Base):
    def test_missing(self):
        self.assertEqual(ClaudeCodeCollector(self.env, self.home).probe()["status"], "missing")

    def test_metadata_only_and_subagent_parent(self):
        proj = self.home / ".claude" / "projects" / "p1"
        write_jsonl(proj / "sess-1.jsonl", [
            {"type": "user", "sessionId": "sess-1", "cwd": "C:/w/app", "entrypoint": "cli", "version": "2.1", "gitBranch": "main",
             "timestamp": "2026-10-01T10:00:00Z", "message": {"role": "user", "content": SECRET}},
            {"type": "assistant", "sessionId": "sess-1", "timestamp": "2026-10-01T10:01:00Z", "message": {"model": "claude-x", "content": SECRET}},
        ])
        write_jsonl(proj / "sess-1" / "subagents" / "agent-a1.jsonl", [
            {"sessionId": "sess-1", "cwd": "C:/w/app", "timestamp": "2026-10-01T10:02:00Z", "message": {"content": SECRET}}])
        collector = ClaudeCodeCollector(self.env, self.home)
        sessions = collector.discover()
        self.assertEqual(len(sessions), 2)
        main = next(s for s in sessions if s.parent_native_id is None)
        sub = next(s for s in sessions if s.parent_native_id)
        self.assertEqual((main.native_id, main.cwd, main.entrypoint, main.version, main.model), ("sess-1", "C:/w/app", "cli", "2.1", "claude-x"))
        self.assertEqual(main.started_at, "2026-10-01T10:00:00+00:00")
        self.assertEqual(sub.parent_native_id, "sess-1")
        self.assertTrue(main.key.startswith("claude:") and main.key.endswith(":sess-1"))
        probe = collector.probe()
        self.assertEqual(probe["status"], "ok")
        self.assertEqual(probe["fields"]["subagent_files"], 1)
        self.assertNotIn(SECRET, repr(sessions) + repr(probe))

    def test_bounded_head_and_unsupported(self):
        proj = self.home / ".claude" / "projects" / "p"
        write_jsonl(proj / "x.jsonl", [{"nothing": 1}])
        self.assertEqual(ClaudeCodeCollector(self.env, self.home).probe()["status"], "unsupported")
        big = proj / "big.jsonl"
        big.write_text(json.dumps({"sessionId": "big", "cwd": "/a"}) + "\n" + ("x" * 600000), encoding="utf-8")
        found = {s.native_id: s for s in ClaudeCodeCollector(self.env, self.home).discover()}
        self.assertEqual(found["big"].cwd, "/a")

    def test_config_dir_env_and_since(self):
        cfg = self.home / "cfg"
        write_jsonl(cfg / "projects" / "p" / "a.jsonl", [{"sessionId": "a", "cwd": "/a"}])
        collector = ClaudeCodeCollector({"CLAUDE_CONFIG_DIR": str(cfg)}, self.home)
        self.assertEqual(len(collector.discover()), 1)
        self.assertEqual(collector.discover(since="2999-01-01T00:00:00Z"), [])


class ClaudeDesktopTests(Base):
    def record(self, **extra):
        data = {"sessionId": "local_1", "cliSessionId": "cli-1", "cwd": "C:/w/d", "model": "m", "createdAt": 1790000000000,
                "lastActivityAt": "2026-10-02T00:00:00Z", "isArchived": True, "title": SECRET, "other": {"x": SECRET}}
        data.update(extra)
        return data

    def test_missing_and_roaming(self):
        self.assertEqual(ClaudeDesktopCollector(self.env, self.home).probe()["status"], "missing")
        base = self.home / "AppData" / "Roaming" / "Claude" / "claude-code-sessions" / "acct" / "org"
        base.mkdir(parents=True)
        (base / "local_a.json").write_text(json.dumps(self.record()), encoding="utf-8")
        collector = ClaudeDesktopCollector(self.env, self.home)
        (s,) = collector.discover()
        self.assertEqual((s.native_id, s.client, s.entrypoint, s.cwd, s.archived), ("cli-1", "claude", "claude-desktop", "C:/w/d", True))
        self.assertTrue(s.started_at.startswith("2026-"))
        self.assertNotIn(SECRET, repr(s) + repr(collector.probe()))
        self.assertNotIn("title", collector.probe()["fields"])

    def test_msix_path_and_large_skipped(self):
        base = self.home / "AppData" / "Local" / "Packages" / "Claude_pzs8" / "LocalCache" / "Roaming" / "Claude" / "claude-code-sessions" / "a"
        base.mkdir(parents=True)
        (base / "local_m.json").write_text(json.dumps(self.record(cliSessionId="cli-m")), encoding="utf-8")
        (base / "local_big.json").write_text(json.dumps(self.record(cliSessionId="big", pad="x" * (1024 * 1024 + 10))), encoding="utf-8")
        collector = ClaudeDesktopCollector(self.env, self.home)
        self.assertEqual([s.native_id for s in collector.discover()], ["cli-m"])
        self.assertEqual(collector.probe()["fields"]["skipped_large"], 1)

    def test_unsupported(self):
        base = self.home / "AppData" / "Roaming" / "Claude" / "claude-code-sessions"
        base.mkdir(parents=True)
        (base / "local_x.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(ClaudeDesktopCollector(self.env, self.home).probe()["status"], "unsupported")


class CodexStateTests(Base):
    def make_db(self, name="state_5.sqlite", columns=None, threads=()):
        home = self.home / ".codex"
        home.mkdir(exist_ok=True)
        columns = columns or "id TEXT, cwd TEXT, created_at INT, updated_at INT, source TEXT, model TEXT, cli_version TEXT, archived INT, rollout_path TEXT, title TEXT"
        db = sqlite3.connect(home / name)
        db.execute(f"CREATE TABLE threads ({columns})")
        db.execute("CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT)")
        for row in threads:
            db.execute("INSERT INTO threads (id, cwd, created_at, updated_at, source, model, archived, title) VALUES (?,?,?,?,?,?,?,?)", row)
        db.execute("INSERT INTO thread_spawn_edges VALUES ('t1','t2')")
        db.commit()
        db.close()

    def test_missing_unsupported_and_ok(self):
        self.assertEqual(CodexStateCollector(self.env, self.home).probe()["status"], "missing")
        self.make_db(columns="id TEXT, cwd TEXT")
        self.assertEqual(CodexStateCollector(self.env, self.home).probe()["status"], "unsupported")

    def test_threads_edges_ms_timestamps_and_highest_suffix(self):
        self.make_db("state_4.sqlite", threads=[("old", "/o", 1, 2, "cli", "m", 0, "t")])
        self.make_db("state_5.sqlite", threads=[
            ("t1", "C:/w/a", 1790000000000, 1790000100000, "cli", "gpt", 0, SECRET),
            ("t2", "C:/w/a", 1790000050, 1790000200, json.dumps({"subagent": {"thread_spawn": {"parent_thread_id": "zzz"}}}), None, 1, SECRET)])
        collector = CodexStateCollector(self.env, self.home)
        probe = collector.probe()
        self.assertEqual((probe["status"], probe["detail"], probe["fields"]["threads"]), ("ok", "state_5.sqlite", 2))
        found = {s.native_id: s for s in collector.discover()}
        self.assertEqual(set(found), {"t1", "t2"})
        self.assertEqual(found["t2"].parent_native_id, "t1")
        self.assertTrue(found["t2"].archived)
        self.assertEqual(found["t2"].entrypoint, "subagent")
        self.assertEqual(found["t1"].entrypoint, "cli")
        self.assertEqual(found["t1"].started_at, to_iso(1790000000))
        self.assertTrue(found["t1"].last_activity.endswith("+00:00"))
        self.assertNotIn(SECRET, repr(found) + repr(probe))


class CodexRolloutTests(Base):
    def test_meta_parent_archived_and_zst(self):
        home = self.home / ".codex"
        meta = lambda i, **p: {"type": "session_meta", "timestamp": "2026-10-03T00:00:00Z", "payload": {"id": i, "cwd": "C:/w/r", "originator": "codex_cli", "cli_version": "1.0", **p}}
        write_jsonl(home / "sessions" / "2026" / "10" / "03" / "rollout-a.jsonl", [meta("r1"), {"type": "message", "payload": {"text": SECRET}}])
        write_jsonl(home / "archived_sessions" / "rollout-b.jsonl", [meta("r2", source={"subagent": {"thread_spawn": {"parent_thread_id": "r1"}}})])
        (home / "sessions" / "rollout-c.jsonl.zst").write_bytes(b"\x28\xb5\x2f\xfd junk")
        write_jsonl(home / "sessions" / "a" / "b" / "c" / "d" / "e" / "f" / "g" / "rollout-deep.jsonl", [meta("deep")])
        collector = CodexRolloutCollector(self.env, self.home)
        found = {s.native_id: s for s in collector.discover()}
        self.assertEqual(set(found), {"r1", "r2"})
        self.assertTrue(found["r2"].archived)
        self.assertEqual(found["r2"].parent_native_id, "r1")
        self.assertEqual((found["r1"].entrypoint, found["r1"].version), ("codex_cli", "1.0"))
        probe = collector.probe()
        self.assertEqual(probe["status"], "ok")
        try:
            import zstandard  # noqa: F401
            self.assertEqual(probe["fields"].get("zst_read"), 1)
        except ImportError:
            self.assertEqual(probe["fields"].get("zst_unread"), 1)
        self.assertNotIn(SECRET, repr(found) + repr(probe))

    def test_missing_and_unsupported(self):
        self.assertEqual(CodexRolloutCollector(self.env, self.home).probe()["status"], "missing")
        write_jsonl(self.home / ".codex" / "sessions" / "rollout-x.jsonl", [{"type": "other"}])
        self.assertEqual(CodexRolloutCollector(self.env, self.home).probe()["status"], "unsupported")


class TapTests(Base):
    def test_missing_and_no_discover(self):
        collector = ClaudeTapCollector(self.env, self.home)
        self.assertEqual(collector.probe()["status"], "missing")
        self.assertEqual(collector.discover(), [])

    def test_not_a_tap_database_is_unsupported(self):
        path = self.home / "tap.sqlite3"
        sqlite3.connect(path).close()
        collector = ClaudeTapCollector({"CLOUDTAP_DB": str(path)}, self.home)
        self.assertEqual(collector.probe()["status"], "unsupported")


class ResolverTests(Base):
    def make_worktree(self, back=None):
        repo = self.home / "repo"
        admin = repo / ".git" / "worktrees" / "wt"
        admin.mkdir(parents=True)
        wt = self.home / "wt"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {admin.as_posix()}\n", encoding="utf-8")
        (admin / "gitdir").write_text((back or (wt / ".git").as_posix()) + "\n", encoding="utf-8")
        return repo, wt

    def test_positive_and_relative(self):
        repo, wt = self.make_worktree()
        self.assertEqual(proven_worktree_main(wt), repo)
        (wt / ".git").write_text("gitdir: ../repo/.git/worktrees/wt\n", encoding="utf-8")
        self.assertEqual(proven_worktree_main(wt), repo)

    def test_back_link_mismatch(self):
        _, wt = self.make_worktree(back=(self.home / "other" / ".git").as_posix())
        self.assertIsNone(proven_worktree_main(wt))

    def test_submodule_and_plain_clone(self):
        repo = self.home / "super"
        module = repo / ".git" / "modules" / "sub"
        module.mkdir(parents=True)
        sub = repo / "sub"
        sub.mkdir()
        (sub / ".git").write_text(f"gitdir: {module.as_posix()}\n", encoding="utf-8")
        (module / "gitdir").write_text((sub / ".git").as_posix(), encoding="utf-8")
        self.assertIsNone(proven_worktree_main(sub))
        self.assertIsNone(proven_worktree_main(repo))  # plain clone: .git is a directory
        self.assertIsNone(proven_worktree_main(self.home / "nothing"))

    def test_under_roots(self):
        root = self.home / "Work"
        (root / "a").mkdir(parents=True)
        self.assertTrue(under_roots(root / "a", [root]))
        self.assertTrue(under_roots(root, [root]))
        self.assertFalse(under_roots(self.home / "Workshop", [root]))
        self.assertFalse(under_roots(root, []))
        if os.name == "nt":
            self.assertTrue(under_roots(str(root / "a").upper(), [str(root).lower()]))


class AggregationTests(Base):
    def test_probe_report_and_registry(self):
        write_jsonl(self.home / ".claude" / "projects" / "p" / "s.jsonl", [{"sessionId": "s", "cwd": "/a", "message": {"content": SECRET}}])
        write_jsonl(self.home / ".claude" / "projects" / "p" / "t.jsonl", [{"sessionId": "t"}])
        report = run_probe(self.env, self.home)
        entry = report["collectors"]["claude_code"]
        self.assertEqual((entry["sessions"], entry["with_cwd"], entry["without_cwd"], entry["distinct_cwds"]), (2, 1, 1, 1))
        self.assertEqual(report["collectors"]["codex_state"]["status"], "missing")
        self.assertEqual(report["totals"]["sessions"], 2)
        blob = json.dumps(report)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn(str(self.home), blob)
        self.assertEqual({c.name for c in all_collectors(self.env, self.home)}, {"claude_code", "claude_desktop", "codex_state", "codex_rollout", "claude_tap"})

    def test_exception_isolation(self):
        class Boom:
            name = "boom"
            def probe(self):
                raise RuntimeError(SECRET)
            def discover(self, since=None, limit=500):
                raise RuntimeError(SECRET)

        good = ClaudeCodeCollector(self.env, self.home)
        probes = probe_all(collectors=[Boom(), good])
        self.assertEqual(probes["boom"]["status"], "unsupported")
        self.assertEqual(probes["claude_code"]["status"], "missing")
        found = discover_all(collectors=[Boom(), good])
        self.assertEqual(found["boom"]["sessions"], [])
        report = run_probe(collectors=[Boom(), good])
        self.assertEqual(report["collectors"]["boom"]["status"], "unsupported")
        self.assertNotIn(SECRET, repr(report) + repr(probes) + repr(found))

    def test_session_info_as_dict(self):
        info = SessionInfo(client="c", collector="x", native_id="n", key="c:00000000:n")
        self.assertEqual(info.as_dict()["archived"], False)
        self.assertIn("parent_native_id", info.as_dict())


if __name__ == "__main__":
    unittest.main()
