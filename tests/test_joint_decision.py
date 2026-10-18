"""Local fixtures only: no production history, credentials, or network required."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "scripts/joint_decision.py"
WRAPPER = SOURCE.parents[2] / "cognition-kb/_工具/joint_decision.py"
spec = importlib.util.spec_from_file_location("joint_decision", SOURCE)
joint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(joint)


class JointDecisionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.personal = self.base / "Sisuself-skill"
        self.knowledge = self.base / "cognition-kb"
        for role, root in (("personal", self.personal), ("knowledge", self.knowledge)):
            root.mkdir()
            self.git(root, "init", "-b", "main")
            self.git(root, "config", "user.name", "Fixture")
            self.git(root, "config", "user.email", "fixture@example.invalid")
            self.git(root, "config", "commit.gpgsign", "false")
            self.git(root, "remote", "add", "origin", "https://github.com/" + joint.REPOSITORIES[role] + ".git")
        self.manifest = {
            "version": 1, "protocol": "integration/decision_protocol.md",
            "repos": {role: {"repository": joint.REPOSITORIES[role], "required_files": paths}
                      for role, paths in (("personal", joint.PERSONAL_FILES), ("knowledge", joint.KNOWLEDGE_FILES))},
            "index": joint.INDEX, "review_files": ["references/september_review.md"],
            "routes": {"business": [joint.B1], "learning": [], "general": []}}
        self.write(self.personal, "integration/manifest.json", json.dumps(self.manifest))
        self.write(self.personal, "integration/decision_protocol.md", "joint protocol")
        for path in joint.PERSONAL_FILES:
            self.write(self.personal, path, "fixture personal context")
        self.write(self.personal, "context/current_state.md", "---\nupdated: 2026-09-30\nas_of: 2026-09-30\nreview_after: 2026-10-16\n---\n\n## 当前短期战略锁\n\n**锁定期：2026-09-30 ～ 2026-10-15。**\n\n不要自动续期。\n")
        self.write(self.personal, "references/september_review.md", "September review")
        self.write(self.personal, "scripts/joint_decision.py", SOURCE.read_text(encoding="utf-8"))
        for path in joint.KNOWLEDGE_FILES:
            self.write(self.knowledge, path, "fixture knowledge context")
        self.records = []
        for number, name in enumerate([joint.B1, "04_精华沉淀/客户机会.md", "04_精华沉淀/客户交付.md", "04_精华沉淀/客户验证.md"]):
            body = "# 客户机会\n完整机制正文：输入→判断→交付→反馈。\n" + str(number)
            self.write(self.knowledge, name, body)
            self.records.append({"id": joint.B1_ID if number == 0 else "fixture-%d" % number,
                                 "title": Path(name).stem, "source": "同一来源", "category": "机会",
                                 "path": name, "head": body, "chars": len(body)})
        self.write(self.knowledge, joint.INDEX, "\n".join(json.dumps(record, ensure_ascii=False) for record in self.records) + "\n")
        if WRAPPER.is_file():
            self.write(self.knowledge, "_工具/joint_decision.py", WRAPPER.read_text(encoding="utf-8"))
        self.personal_sha = self.commit(self.personal)
        self.knowledge_sha = self.commit(self.knowledge)
        self.queue = self.base / "private-queue"

    @staticmethod
    def git(root, *args):
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL).decode().strip()

    @staticmethod
    def write(root, path, content):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self, root):
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", "fixture")
        return self.git(root, "rev-parse", "HEAD")

    def command(self, arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = joint.main(arguments)
        return status, json.loads(output.getvalue())

    def load(self, *extra):
        return self.command(["load", "--question", "商业客户机会", "--personal-repo", str(self.personal),
                             "--knowledge-repo", str(self.knowledge), "--as-of", "2026-10-18", *extra])

    def feedback(self, record):
        path = self.base / "input.json"
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return self.command(["feedback", "--input", str(path), "--queue-dir", str(self.queue)])

    @staticmethod
    def record(**changes):
        record = {"id": "fixture-D1", "kind": "decision", "summary": "fixture decision",
                  "event_date": "2026-10-18", "source_ids": ["fixture-user-1"],
                  "status": "confirmed", "scope": "both"}
        record.update(changes)
        return record

    def test_complete_version_pinned_ignores_worktree(self):
        self.write(self.personal, "context/profile.md", "UNCOMMITTED PRIVATE CONTENT")
        status, packet = self.load()
        self.assertEqual(status, 0)
        self.assertTrue(packet["complete"])
        self.assertEqual(packet["repos"]["personal"]["sha"], self.personal_sha)
        self.assertNotIn("UNCOMMITTED", json.dumps(packet))
        self.assertEqual(packet["repos"]["knowledge"]["sha"], self.knowledge_sha)
        self.assertTrue(packet["repos"]["personal"]["origin_verified"])
        self.assertFalse(packet["repos"]["personal"]["verified_remote"])
        self.assertTrue(packet["repos"]["personal"]["working_tree_ignored"])
        self.assertEqual({d["repository_sha"] for d in packet["documents"] if d["repo"] == "personal"}, {self.personal_sha})
        self.write(self.personal, "context/profile.md", "LATER COMMIT")
        self.commit(self.personal)
        _, pinned = self.load("--personal-ref", self.personal_sha)
        self.assertNotIn("LATER COMMIT", json.dumps(pinned))

    def test_b1_full_body_three_search_hits_and_no_evidence_inflation(self):
        _, packet = self.load()
        b1 = next(d for d in packet["documents"] if d["path"] == joint.B1)
        self.assertIn("完整机制正文", b1["content"])
        self.assertEqual(b1["source_ids"], [joint.B1_ID])
        index = next(d for d in packet["documents"] if d["path"] == joint.INDEX)
        self.assertEqual(len(index["matches"]), 3)
        self.assertNotIn("content", index)
        self.assertTrue(any(w["code"] == "evidence_boundary" for w in packet["warnings"]))

    def test_expiry_and_metadata_only(self):
        _, packet = self.load("--metadata-only")
        codes = {w["code"] for w in packet["warnings"]}
        self.assertTrue({"state_review_expired", "strategy_lock_expired"} <= codes)
        self.assertEqual(packet["repos"]["personal"]["strategy_lock_until"], "2026-10-15")
        self.assertTrue(all("content" not in d and "matches" not in d for d in packet["documents"]))

    def test_missing_repository_and_bad_origin_are_partial(self):
        status, packet = self.load("--personal-repo", str(self.base / "missing"))
        self.assertEqual(status, 2)
        self.assertFalse(packet["complete"])
        self.assertTrue(any(d["repo"] == "knowledge" for d in packet["documents"]))
        self.git(self.personal, "remote", "set-url", "origin", "https://github.com/wrong/repository.git")
        status, packet = self.load()
        self.assertEqual(status, 2)
        self.assertFalse(packet["repos"]["personal"]["verified_remote"])
        self.assertFalse(any(d["repo"] == "personal" for d in packet["documents"]))

    def test_missing_required_file_preserves_partial_read(self):
        (self.personal / "context/principles.md").unlink()
        self.commit(self.personal)
        status, packet = self.load()
        self.assertEqual(status, 2)
        self.assertTrue(any(m["path"] == "context/principles.md" for m in packet["missing"]))
        self.assertTrue(any(d["path"] == "context/profile.md" for d in packet["documents"]))

    def test_entry_equivalence(self):
        if not (self.knowledge / "_工具/joint_decision.py").is_file():
            self.skipTest("Sibling cognition-kb wrapper is not installed")
        common = ["load", "--question", "九月商业复盘", "--personal-repo", str(self.personal),
                  "--knowledge-repo", str(self.knowledge), "--as-of", "2026-10-18", "--metadata-only"]
        direct = subprocess.check_output([sys.executable, str(SOURCE), *common])
        wrapped = subprocess.check_output([sys.executable, str(self.knowledge / "_工具/joint_decision.py"), *common])
        self.assertEqual(json.loads(direct), json.loads(wrapped))

    def test_review_relevance(self):
        _, review = self.load("--question", "九月商业复盘")
        self.assertTrue(any(d["path"] == "references/september_review.md" for d in review["documents"]))
        _, ordinary = self.load("--topic", "general")
        self.assertFalse(any(d["path"] == "references/september_review.md" for d in ordinary["documents"]))

    def test_refresh_only_fetches_and_explicit_ref_wins(self):
        original = joint.git
        seen = []
        def recorded(root, *args):
            seen.append(args)
            if args[0] == "fetch":
                return b""
            return original(root, *args)
        for root in (self.personal, self.knowledge):
            self.git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
        with mock.patch.object(joint, "git", side_effect=recorded):
            status, packet = self.load("--refresh", "--personal-ref", self.personal_sha)
        self.assertEqual(status, 0)
        self.assertEqual(packet["repos"]["personal"]["ref"], self.personal_sha)
        self.assertEqual(packet["repos"]["knowledge"]["ref"], "origin/main")
        self.assertTrue(all(meta["origin_verified"] and meta["verified_remote"] for meta in packet["repos"].values()))
        self.assertEqual(sum(args[0] == "fetch" for args in seen), 2)
        self.assertFalse(any(args[0] in ("push", "pull", "checkout", "reset", "commit") for args in seen))

    def test_feedback_idempotent_reference_only_and_conflict_rejected(self):
        before = {root: self.git(root, "rev-parse", "HEAD") for root in (self.personal, self.knowledge)}
        status, result = self.feedback(self.record())
        self.assertEqual(status, 0)
        self.assertEqual(len(result["queued"]), 2)
        personal = json.loads((self.queue / "personal.jsonl").read_text())
        knowledge = json.loads((self.queue / "knowledge.jsonl").read_text())
        self.assertIn("context/decision_log.md", personal["target_files"])
        self.assertNotIn("summary", knowledge)
        self.assertEqual(knowledge["reference_id"], personal["id"])
        status, result = self.feedback(self.record())
        self.assertEqual(status, 0)
        self.assertEqual(result["queued"], [])
        status, _ = self.feedback(self.record(summary="conflicting"))
        self.assertEqual(status, 2)
        self.assertEqual(len((self.queue / "personal.jsonl").read_text().splitlines()), 1)
        self.assertEqual(before, {root: self.git(root, "rev-parse", "HEAD") for root in before})

    def test_feedback_candidates_methods_supersedes_and_invalid_inputs(self):
        _, result = self.feedback(self.record(status="candidate", scope="personal"))
        self.assertNotIn("context/decision_log.md", result["queued"][0]["target_files"])
        _, result = self.feedback(self.record(id="fixture-M1", kind="method", supersedes="fixture-D1",
                                              source_ids=[joint.B1_ID]))
        knowledge = [json.loads(line) for line in (self.queue / "knowledge.jsonl").read_text().splitlines()]
        self.assertEqual(knowledge[0]["summary"], "fixture decision")
        self.assertEqual(knowledge[0]["supersedes"], "fixture-D1")
        self.assertIn(joint.B1, knowledge[0]["target_files"])
        for changes in ({"source_ids": []}, {"event_date": ""}, {"kind": "unknown"},
                        {"event_date": "2026-02-31"}, {"scope": "knowledge"}):
            status, _ = self.feedback(self.record(id="invalid", **changes))
            self.assertEqual(status, 2)
        self.assertEqual(len((self.queue / "personal.jsonl").read_text().splitlines()), 2)

    def test_generic_method_does_not_target_b1(self):
        _, result = self.feedback(self.record(id="generic-method", kind="method", scope="knowledge",
                                              source_ids=["essence-0003"]))
        self.assertNotIn(joint.B1, result["queued"][0]["target_files"])
        self.assertIn("source_ids", result["routing_note"])
        _, observation = self.feedback(self.record(id="observation", kind="observation", scope="personal"))
        self.assertIn("context/current_state.md", observation["queued"][0]["target_files"])

    def test_no_read_operation_changes_repository_refs_or_origin(self):
        before = [(self.git(root, "show-ref"), self.git(root, "remote", "get-url", "origin"))
                  for root in (self.personal, self.knowledge)]
        self.load()
        after = [(self.git(root, "show-ref"), self.git(root, "remote", "get-url", "origin"))
                 for root in (self.personal, self.knowledge)]
        self.assertEqual(before, after)

    def test_documented_product_channel_question_uses_business_route(self):
        _, packet = self.load("--question", "先开发产品还是先验证渠道与验收？")
        self.assertEqual(packet["topic"], "business")
        self.assertTrue(any(d["path"] == joint.B1 and "完整机制正文" in d["content"]
                            for d in packet["documents"]))

    def test_fetch_failure_is_partial_and_not_remote_verified(self):
        original = joint.git
        def unavailable(root, *args):
            if args[0] == "fetch":
                raise ValueError("fixture network unavailable")
            return original(root, *args)
        with mock.patch.object(joint, "git", side_effect=unavailable):
            status, packet = self.load("--refresh", "--personal-ref", "HEAD", "--knowledge-ref", "HEAD")
        self.assertEqual(status, 2)
        self.assertFalse(packet["complete"])
        self.assertTrue(packet["documents"])
        self.assertTrue(all(meta["origin_verified"] and not meta["verified_remote"] for meta in packet["repos"].values()))

    def test_bad_manifest_types_return_partial(self):
        for value in ([], {"version": 1, "repos": []},
                      dict(self.manifest, review_files="not a list"),
                      dict(self.manifest, routes={"business": "not a list"})):
            with self.subTest(value=value):
                self.write(self.personal, "integration/manifest.json", json.dumps(value))
                self.commit(self.personal)
                status, packet = self.load()
                self.assertEqual(status, 2)
                self.assertTrue(any(m["path"] == "integration/manifest.json" for m in packet["missing"]))
                self.assertTrue(packet["documents"])

    def test_bad_index_fields_are_not_used_for_search(self):
        for changes in ({"chars": -1}, {"chars": True}, {"chars": "12"}, {"head": []}):
            with self.subTest(changes=changes):
                records = [dict(record) for record in self.records]
                records[-1].update(changes)
                self.write(self.knowledge, joint.INDEX, "\n".join(json.dumps(r) for r in records) + "\n")
                self.commit(self.knowledge)
                status, packet = self.load()
                self.assertEqual(status, 2)
                index = next(d for d in packet["documents"] if d["path"] == joint.INDEX)
                self.assertEqual(index["matches"], [])
                self.assertEqual(index["entry_count"], 0)

    def test_default_date_uses_shanghai_and_explicit_date_still_wins(self):
        instant = joint.dt.datetime(2026, 10, 16, 0, 30)
        arguments = ["load", "--question", "商业客户机会", "--personal-repo", str(self.personal),
                     "--knowledge-repo", str(self.knowledge), "--metadata-only"]
        with mock.patch.object(joint.dt, "datetime") as clock:
            clock.now.return_value = instant
            status, packet = self.command(arguments)
            zone = clock.now.call_args.args[0]
            self.assertEqual(zone.utcoffset(None).total_seconds(), 8 * 3600)
        self.assertEqual(status, 0)
        self.assertFalse(any(w["code"] == "state_review_expired" for w in packet["warnings"]))
        _, overridden = self.command(arguments + ["--as-of", "2026-10-18"])
        self.assertTrue(any(w["code"] == "state_review_expired" for w in overridden["warnings"]))

    def test_full_context_output_is_private_even_for_existing_file(self):
        path = self.base / "packet.json"
        path.write_text("placeholder")
        path.chmod(0o644)
        with contextlib.redirect_stdout(io.StringIO()):
            status = joint.main(["load", "--question", "商业客户机会", "--personal-repo", str(self.personal),
                                 "--knowledge-repo", str(self.knowledge), "--output", str(path)])
        self.assertEqual(status, 0)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(json.loads(path.read_text())["complete"])

    def test_business_semantics_prefer_curated_frameworks_over_noisy_job_and_case_matches(self):
        queries = [
            "我想用 AI 做一个小工具，再通过内容传播找到付费用户。应该先开发产品，还是先验证渠道、交付和验收？请结合我的个人条件和已有认知给出有主次的判断，指出尚不知道什么。",
            "九月我想把开源工具、内容传播和资源机会串起来。现在想做一款 AI 小产品承接流量，怎样判断该投入多少，哪些条件没打通前应该先停？结合我的个人目标与认知材料给一个有主次的判断。",
        ]
        rows = [dict(record) for record in self.records]
        for rid, title in (("fixture-s3", "S3 流量与私域"), ("fixture-s6", "S6 项目落地实操")):
            path = "04_精华沉淀/" + title + ".md"
            self.write(self.knowledge, path, "完整的主题方法正文")
            rows.append({"id": rid, "title": title, "source": "精华沉淀（提炼成品）", "category": "",
                         "path": path, "head": "主题方法", "chars": 10})
        for rid, source, title in (("job-noise", "求职资料", "产品面试应该怎么问？怎么答？"),
                                   ("pianmen-noise", "偏门资料", "一个人的小生意与流量项目怎么做")):
            path = "06_资料原件/_md/" + source + "/" + title + ".md"
            self.write(self.knowledge, path, "高噪声资料")
            rows.append({"id": rid, "title": title, "source": source, "category": "个人条件与项目",
                         "path": path, "head": " ".join(queries), "chars": 6})
        self.write(self.knowledge, joint.INDEX, "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n")
        self.commit(self.knowledge)
        expected = [{"fixture-s3", "fixture-s6"}, {"fixture-s3", "fixture-s6", joint.B1_ID}]
        for question, ids in zip(queries, expected):
            with self.subTest(question=question):
                _, packet = self.load("--question", question)
                index = next(d for d in packet["documents"] if d["path"] == joint.INDEX)
                self.assertEqual({row["id"] for row in index["matches"]}, ids)
                self.assertFalse(any(row["source"] == "求职资料" for row in index["matches"]))
        self.assertFalse(joint.query_terms("请结合我的个人条件给出有主次的判断，指出尚不知道什么。"))

    def test_business_excludes_job_source_unless_explicitly_requested(self):
        row = dict(self.records[1], id="job-noise", source="求职资料",
                   title="客户机会", path="06_资料原件/_md/求职资料/客户机会.md")
        self.assertEqual(joint.rank_records([row], "商业客户机会", "business"), [])
        self.assertEqual(joint.rank_records([row], "客户机会求职面试", "business"), [row])

    def test_framework_copy_and_original_share_one_content_body(self):
        original = "04_精华沉淀/A1 刘勇 · AI创投与技术周期.md"
        copied = "08_AI知识包/02_框架库/A1 刘勇 · AI创投与技术周期.md"
        for path in (original, copied):
            self.write(self.knowledge, path, "同一份完整战略框架")
        self.manifest["routes"]["business"].append(copied)
        self.write(self.personal, "integration/manifest.json", json.dumps(self.manifest))
        rows = self.records + [{"id": "ly2026-a1", "title": Path(original).stem,
                                "source": "独立来源", "category": "战略", "path": original,
                                "head": "赛道成本", "chars": 10}]
        self.write(self.knowledge, joint.INDEX, "\n".join(json.dumps(row) for row in rows) + "\n")
        self.commit(self.personal)
        self.commit(self.knowledge)
        _, packet = self.load("--question", "商业赛道成本")
        documents = [d for d in packet["documents"] if d["source_ids"] == ["ly2026-a1"]]
        self.assertEqual(len(documents), 2)
        self.assertEqual(sum("content" in d for d in documents), 1)
        self.assertEqual(next(d for d in documents if "content_ref" in d)["content_ref"]["path"], copied)


if __name__ == "__main__":
    unittest.main()
