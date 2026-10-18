#!/usr/bin/env python3
"""Read two version-pinned repositories; queue feedback locally, never publish it."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


REPOSITORIES = {"personal": "Sisu-z/Sisuself-skill",
                "knowledge": "Sisu-z/cognition-kb"}
PERSONAL_FILES = ["context/%s.md" % name for name in
                  ("profile", "current_state", "principles", "cognitive_model",
                   "decision_log", "sources")]
KNOWLEDGE_FILES = ["08_AI知识包/00_AI_GUIDE.md", "08_AI知识包/01_INDEX_概览.md"]
INDEX = "08_AI知识包/01_INDEX.jsonl"
B1 = "04_精华沉淀/B1 个人实践 · 机会判断与交付复盘.md"
B1_ID = "sisu202609-b1"
CURATED_ROUTES = [
    ("S3 流量与私域", ("内容", "渠道", "流量", "传播", "私域", "获客")),
    ("S6 项目落地实操", ("交付", "验收", "投入", "预算", "项目落地")),
    ("B1 个人实践", ("开源", "九月", "9月", "复盘", "责任", "交易")),
    ("S1 销售力", ("销售", "报价", "沟通", "成交", "谈单")),
    ("A1 刘勇", ("策略", "赛道", "稀缺", "成本", "技术周期", "战略")),
]
CAREER_QUERY = r"求职|找工作|应聘|招聘|面试|简历|谈薪|职业|岗位|job|interview"
STOP_WORDS = set("我想用 我想 应该 先开发 还是 请结合 结合 我的 个人条件 个人目标 个人 已有认知 认知材料 认知 给出 有主次 主次 判断 指出 尚不知道 不知道 什么 现在 想做 一款 一个 怎样 多少 哪些 条件 没打通 打通 前应该 前应 应该 先停 再通过 通过 找到 串起来 起来 能不能 可以 帮我 请 已有 尚不 业务 商业".split())


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=60)
    if result.returncode:
        # Do not print remote URLs, which can contain credentials.
        raise ValueError("git %s failed (exit %d)" % (args[0], result.returncode))
    return result.stdout


def valid_origin(origin, expected):
    origin = origin.strip().rstrip("/")
    if origin.endswith(".git"):
        origin = origin[:-4]
    return origin.lower() in {
        ("https://github.com/" + expected).lower(),
        ("http://github.com/" + expected).lower(),
        ("git@github.com:" + expected).lower(),
        ("ssh://git@github.com/" + expected).lower(),
    }


def safe_path(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("invalid repository-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value.startswith("-"):
        raise ValueError("invalid repository-relative path")
    return value


def validate_manifest(manifest):
    if not isinstance(manifest, dict) or type(manifest.get("version")) is not int or manifest["version"] != 1:
        raise ValueError("manifest must be an object with version 1")
    repos, routes = manifest.get("repos"), manifest.get("routes")
    if not isinstance(repos, dict) or not isinstance(routes, dict):
        raise ValueError("manifest repos/routes must be objects")
    for repo, expected in REPOSITORIES.items():
        config = repos.get(repo)
        if not isinstance(config, dict) or config.get("repository") != expected:
            raise ValueError("manifest repository mismatch: " + repo)
        paths = config.get("required_files")
        if not isinstance(paths, list):
            raise ValueError("required_files must be a list")
        for path in paths:
            safe_path(path)
    for topic in ("business", "learning", "general"):
        paths = routes.get(topic)
        if not isinstance(paths, list):
            raise ValueError("route must be a file list: " + topic)
        for path in paths:
            safe_path(path)
    reviews = manifest.get("review_files", [])
    if not isinstance(reviews, list):
        raise ValueError("review_files must be a list")
    for path in reviews:
        safe_path(path)
    safe_path(manifest.get("protocol", "integration/decision_protocol.md"))
    safe_path(manifest.get("index", INDEX))


class Packet:
    def __init__(self, args):
        self.args = args
        self.result = {"question": args.question, "topic": choose_topic(args),
                       "repos": {}, "documents": [], "warnings": [], "missing": [],
                       "complete": False}
        self.roots = {"personal": Path(args.personal_repo).expanduser(),
                      "knowledge": Path(args.knowledge_repo).expanduser()}
        self.cache = {}

    def missing(self, repo, path, reason):
        item = {"repo": repo, "path": path, "reason": reason}
        if item not in self.result["missing"]:
            self.result["missing"].append(item)

    def snapshot(self, repo):
        expected = REPOSITORIES[repo]
        explicit = getattr(self.args, repo + "_ref")
        ref = explicit or ("origin/main" if self.args.refresh else "HEAD")
        meta = {"repository": expected, "sha": None, "ref": ref,
                "origin_verified": False, "verified_remote": False}
        self.result["repos"][repo] = meta
        try:
            root = self.roots[repo]
            origin = git(root, "remote", "get-url", "origin").decode("utf-8").strip()
            if not valid_origin(origin, expected):
                raise ValueError("origin does not match " + expected)
            meta["origin_verified"] = True
            if self.args.refresh:
                try:
                    git(root, "fetch", "origin", "main")
                    meta["verified_remote"] = True
                except (ValueError, OSError, subprocess.TimeoutExpired) as error:
                    self.missing(repo, "", "refresh unavailable: " + str(error))
            if not meta["verified_remote"]:
                self.result["warnings"].append({
                    "code": "remote_unverified", "repo": repo,
                    "message": "未联网核验远端；只能报告本地指定提交，不能声称是最新 main。"})
            meta["sha"] = git(root, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
            meta["working_tree_ignored"] = bool(git(root, "status", "--porcelain"))
        except (ValueError, OSError, subprocess.TimeoutExpired, UnicodeError) as error:
            self.missing(repo, "", str(error))

    def read(self, repo, path):
        key = (repo, path)
        if key in self.cache:
            return self.cache[key]
        sha = self.result["repos"][repo]["sha"]
        if not sha:
            return None
        try:
            safe_path(path)
            data = git(self.roots[repo], "show", sha + ":" + path)
            content = data.decode("utf-8", errors="strict")
            self.cache[key] = content
            self.result["documents"].append({
                "repo": repo, "path": path, "source_ids": [], "content": content,
                "sha256": hashlib.sha256(data).hexdigest(), "repository_sha": sha})
            return content
        except (ValueError, OSError, subprocess.TimeoutExpired, UnicodeError) as error:
            self.missing(repo, path, str(error))
            self.cache[key] = None
            return None

    def document(self, repo, path):
        return next((d for d in self.result["documents"]
                     if d["repo"] == repo and d["path"] == path), None)

    def load(self):
        for repo in REPOSITORIES:
            self.snapshot(repo)
        raw = self.read("personal", "integration/manifest.json")
        manifest = {}
        if raw is not None:
            try:
                manifest = json.loads(raw)
                validate_manifest(manifest)
            except (ValueError, KeyError, TypeError) as error:
                self.missing("personal", "integration/manifest.json", str(error))
                manifest = {}
        self.read("personal", manifest.get("protocol", "integration/decision_protocol.md"))
        for repo, fallback in (("personal", PERSONAL_FILES), ("knowledge", KNOWLEDGE_FILES)):
            declared = manifest.get("repos", {}).get(repo, {}).get("required_files", [])
            for path in dict.fromkeys(fallback + declared):
                self.read(repo, path)
        topic = self.result["topic"]
        for path in manifest.get("routes", {}).get(topic, []):
            self.read("knowledge", path)
        if topic == "business":
            self.read("knowledge", B1)
        if re.search(r"九月|9月|九月份|2026-09|September|认知|复盘|反思|原则|策略",
                     self.args.question, re.I):
            for path in manifest.get("review_files", []):
                self.read("personal", path)
        self.check_state()
        self.search(manifest.get("index", INDEX))
        self.result["complete"] = not self.result["missing"]
        if self.args.metadata_only:
            for document in self.result["documents"]:
                document.pop("content", None)
                document.pop("matches", None)
        return self.result

    def check_state(self):
        text = self.cache.get(("personal", "context/current_state.md")) or ""
        meta = self.result["repos"]["personal"]
        today = self.args.as_of
        for field in ("updated", "as_of", "review_after"):
            match = re.search(r"^" + field + r":\s*[\"']?(\d{4}-\d{2}-\d{2})", text, re.M)
            if match:
                meta[field] = match.group(1)
        dates = []
        lock = re.search(r"^## 当前短期战略锁\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        if lock:
            # The range is conventionally the first dated line in the section.
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", lock.group(1))[:2]
        if dates:
            meta["strategy_lock_until"] = dates[-1]
        for field, code in (("review_after", "state_review_expired"),
                            ("strategy_lock_until", "strategy_lock_expired")):
            if field in meta and meta[field] < today:
                self.result["warnings"].append({
                    "code": code, "repo": "personal", "date": meta[field],
                    "message": "状态需复查；不能自动延长旧战略锁或推断新的主线。"})
        self.result["warnings"].append({
            "code": "evidence_boundary", "message":
            "用户表达、来源转述与外部核验须分开；来源同名或重复说法不构成新增独立证据。"})

    def search(self, path):
        text = self.read("knowledge", path)
        if text is None:
            return
        records, ids, paths = [], set(), set()
        try:
            for line in text.splitlines():
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("index record must be an object")
                for field in ("id", "title", "source", "category", "path", "head"):
                    if not isinstance(record.get(field), str):
                        raise ValueError("index field must be a string: " + field)
                if not record["id"] or not record["title"] or not record["source"]:
                    raise ValueError("index id/title/source must be nonempty")
                if type(record.get("chars")) is not int or record["chars"] < 0:
                    raise ValueError("index chars must be a nonnegative integer")
                safe_path(record["path"])
                if record["id"] in ids or record["path"] in paths:
                    raise ValueError("duplicate index id/path")
                ids.add(record["id"])
                paths.add(record["path"])
                records.append(record)
        except (ValueError, TypeError) as error:
            self.missing("knowledge", path, "invalid index: " + str(error))
            records = []
        hits = rank_records(records, self.args.question, self.result["topic"])
        for record in hits:
            self.read("knowledge", record["path"])
            doc = self.document("knowledge", record["path"])
            if doc:
                doc["source_ids"] = [record["id"]]
        if self.result["topic"] == "business":
            b1 = next((r for r in records if r["path"] == B1), None)
            if b1 is None or b1["id"] != B1_ID:
                self.missing("knowledge", path, "B1 stable index entry missing or mismatched")
        for document in self.result["documents"]:
            if document["repo"] == "knowledge" and document["path"] != path:
                # Framework copies bridge to the original record by unique title.
                candidates = [r for r in records if r["path"] == document["path"]]
                if not candidates:
                    candidates = [r for r in records if r["title"] == PurePosixPath(document["path"]).stem]
                if len(candidates) == 1:
                    document["source_ids"] = [candidates[0]["id"]]
        seen_content = {}
        for document in self.result["documents"]:
            if document["repo"] != "knowledge" or not document["source_ids"] or "content" not in document:
                continue
            key = (tuple(document["source_ids"]), document["sha256"])
            if key in seen_content:
                document.pop("content")
                document["content_ref"] = {"repo": "knowledge", "path": seen_content[key],
                                           "source_id": document["source_ids"][0]}
            else:
                seen_content[key] = document["path"]
        index_doc = self.document("knowledge", path)
        index_doc.pop("content", None)
        index_doc.update({"entry_count": len(records), "matches": hits,
                          "content_omitted": "full index used for search; matched source documents included"})


def query_terms(question):
    cleaned = question.lower()
    for word in sorted(STOP_WORDS, key=len, reverse=True):
        cleaned = cleaned.replace(word, " ")
    words = re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", cleaned)
    terms = set(term for word in words for term in
                ([word] + [word[i:i + 2] for i in range(len(word) - 1)]
                 if re.search(r"[\u4e00-\u9fff]", word) else [word]))
    return terms - STOP_WORDS - {"what", "how", "can", "my", "should", "want", "please",
                                 "with", "the", "and", "or", "to", "for"}


def term_matches(term, text):
    text = text.lower()
    if re.fullmatch(r"[a-z0-9_]+", term):
        return re.search(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])", text) is not None
    return term in text


def rank_records(records, question, topic):
    career = re.search(CAREER_QUERY, question, re.I) is not None
    allowed = [record for record in records if not (topic == "business" and not career and
               (record["id"].startswith("job-") or record["source"] == "求职资料"
                or "/_md/求职资料/" in record["path"]))]
    curated = []
    if topic == "business" and not career:
        for prefix, keywords in CURATED_ROUTES:
            matched = sum(word in question.lower() for word in keywords)
            if matched:
                curated.extend((matched, record) for record in allowed
                               if record["path"].startswith("04_精华沉淀/")
                               and record["title"].startswith(prefix))
    if curated:
        # A broad decision question needs relevant frameworks, not loosely matched
        # old examples. Do not fill the remaining slots just to return three hits.
        return [record for _, record in sorted(curated, key=lambda pair: (-pair[0], pair[1]["id"]))[:3]]
    terms, scored = query_terms(question), []
    for record in allowed:
        matches = {field: {term for term in terms if term_matches(term, record[field])}
                   for field in ("title", "head", "category")}
        distinct = set().union(*matches.values())
        if len(distinct) < 2 or not matches["title"]:
            continue
        score = sum(weight * len(matches[field]) for field, weight in
                    (("title", 5), ("head", 2), ("category", 1)))
        if record["path"].startswith("04_精华沉淀/") and "/_迭代/" not in record["path"]:
            score += 10
        scored.append((score, record))
    return [record for _, record in sorted(scored, key=lambda pair: (-pair[0], pair[1]["id"]))[:3]]


def choose_topic(args):
    if args.topic != "auto":
        return args.topic
    if re.search(r"商业|创业|赚钱|生意|客户|获客|营收|收入|销售|营销|机会判断|产品|渠道|交付|验收|business|startup", args.question, re.I):
        return "business"
    if re.search(r"学习|科研|技术路线|专业|学业|编程|考研|职业|实习|learning|career", args.question, re.I):
        return "learning"
    return "general"


def validate_feedback(record):
    required = {"id", "kind", "summary", "event_date", "source_ids", "status", "scope"}
    if not isinstance(record, dict) or not required <= record.keys():
        raise ValueError("feedback requires id/kind/summary/event_date/source_ids/status/scope")
    if set(record) - required - {"supersedes"}:
        raise ValueError("unsupported feedback fields")
    for field in ("id", "summary"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise ValueError("feedback " + field + " must be nonempty")
    if record["kind"] not in ("decision", "observation", "correction", "method"):
        raise ValueError("invalid feedback kind")
    if record["status"] not in ("candidate", "confirmed"):
        raise ValueError("invalid feedback status")
    if record["scope"] not in ("personal", "knowledge", "both"):
        raise ValueError("invalid feedback scope")
    if record["kind"] == "decision" and record["scope"] == "knowledge":
        raise ValueError("personal decisions require scope personal or both")
    if not isinstance(record["source_ids"], list) or not record["source_ids"] or any(
            not isinstance(value, str) or not value.strip() for value in record["source_ids"]):
        raise ValueError("feedback requires nonempty source_ids")
    if not isinstance(record["event_date"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["event_date"]):
        raise ValueError("feedback requires ISO event_date")
    dt.date.fromisoformat(record["event_date"])
    if "supersedes" in record and (not isinstance(record["supersedes"], str)
                                   or not record["supersedes"].strip()
                                   or record["supersedes"] == record["id"]):
        raise ValueError("invalid supersedes reference")


def feedback_targets(record, repo):
    if repo == "personal":
        if record["kind"] == "decision" and record["status"] == "confirmed":
            return ["context/decision_log.md", "context/current_state.md"]
        if record["kind"] == "observation" and record["status"] == "confirmed":
            return ["context/current_state.md", "context/sources.md"]
        return ["context/cognitive_model.md", "context/sources.md"]
    targets = ["04_精华沉淀/_迭代/来源登记.md", "04_精华沉淀/_迭代/待裁决.md"]
    if record["kind"] == "method" and any(source == B1_ID or source.startswith("B1-")
                                          for source in record["source_ids"]):
        targets.append("04_精华沉淀/B1 个人实践 · 机会判断与交付复盘.md")
    return targets


def enqueue_feedback(args):
    value = json.loads(Path(args.input).read_text(encoding="utf-8"))
    records = value if isinstance(value, list) else [value]
    if not records:
        raise ValueError("feedback input is empty")
    planned = {"personal": {}, "knowledge": {}}
    for record in records:
        validate_feedback(record)
        scope = record["scope"]
        primary = ("knowledge" if record["kind"] == "method" else "personal") if scope == "both" else scope
        for repo in (("personal", "knowledge") if scope == "both" else (scope,)):
            item = dict(record) if repo == primary else {
                "id": record["id"], "record_type": "reference", "reference_id": record["id"],
                "primary_repo": primary, "source_ids": record["source_ids"],
                "event_date": record["event_date"], "kind": record["kind"], "status": record["status"]}
            item.update({"target_repo": REPOSITORIES[repo],
                         "target_files": feedback_targets(record, repo)})
            if record["id"] in planned[repo] and planned[repo][record["id"]] != item:
                raise ValueError("conflicting feedback id: " + record["id"])
            planned[repo][record["id"]] = item
    directory = Path(args.queue_dir).expanduser().resolve()
    if any((parent / ".git").exists() for parent in [directory, *directory.parents]):
        raise ValueError("queue-dir must be outside Git repositories; use a private local directory")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Serialise local queue writers; recovery is idempotent after a partial append.
    import fcntl
    descriptor = os.open(str(directory / ".feedback.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    added, existing = [], []
    with os.fdopen(descriptor, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = {}
        for repo in REPOSITORIES:
            path = directory / (repo + ".jsonl")
            previous[repo] = {}
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    row = json.loads(line)
                    if row["id"] in previous[repo] and previous[repo][row["id"]] != row:
                        raise ValueError("conflicting existing queue id: " + row["id"])
                    previous[repo][row["id"]] = row
            for rid, row in planned[repo].items():
                if rid in previous[repo] and previous[repo][rid] != row:
                    raise ValueError("conflicting feedback id: " + rid)
        for repo in REPOSITORIES:
            for rid, row in planned[repo].items():
                if rid in previous[repo]:
                    existing.append({"repo": repo, "id": rid})
                    continue
                descriptor = os.open(str(directory / (repo + ".jsonl")),
                                     os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                added.append({"repo": repo, "id": rid, "target_repo": row["target_repo"],
                              "target_files": row["target_files"]})
    return {"queued": added, "already_queued": existing, "published": False,
            "routing_note": "target_files 是候选；应用者须按 source_ids 查询主索引定位对应正文，不能机械全部写入。",
            "message": "Local feedback queue only; repository content and remotes unchanged."}


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("load")
    load.add_argument("--question", required=True)
    load.add_argument("--personal-repo", default=str(root))
    load.add_argument("--knowledge-repo", default=str(root.parent / "cognition-kb"))
    load.add_argument("--personal-ref", help="default HEAD; origin/main with --refresh")
    load.add_argument("--knowledge-ref", help="default HEAD; origin/main with --refresh")
    load.add_argument("--refresh", action="store_true")
    load.add_argument("--metadata-only", action="store_true")
    load.add_argument("--topic", choices=("auto", "business", "learning", "general"), default="auto")
    load.add_argument("--as-of", default=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat())
    load.add_argument("--output")
    feedback = commands.add_parser("feedback")
    feedback.add_argument("--input", required=True)
    feedback.add_argument("--queue-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "load":
            dt.date.fromisoformat(args.as_of)
            result = Packet(args).load()
        else:
            result = enqueue_feedback(args)
        output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if getattr(args, "output", None):
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                                 0o644 if args.metadata_only else 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                if not args.metadata_only:
                    os.fchmod(stream.fileno(), 0o600)
                stream.write(output)
        else:
            sys.stdout.write(output)
        return 0 if result.get("complete", True) else 2
    except (ValueError, OSError, TypeError, KeyError) as error:
        sys.stdout.write(json.dumps({"complete": False, "error": str(error)}, ensure_ascii=False) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
