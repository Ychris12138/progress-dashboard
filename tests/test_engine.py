import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from dashboard.core import *
from dashboard.engine import *
from dashboard.render import presentation, build
from dashboard.sources import capture, validate_source


ROOT = Path(__file__).resolve().parents[1]


def sample_draft(draft_id="draft_one", **changes):
    value = {"schema_version": 1, "draft_id": draft_id, "project_id": "proj_demo", "record_type": "progress",
             "occurred_at": "2026-11-12", "summary": "完成数据模型设计", "state_as_of": "2026-11-12",
             "state_snapshot": {"status": "active", "next_step": "编写导入工具", "blocker": None},
             "source": None, "evidence": "人工确认的测试记录", "verification": "confirmed", "revision": None}
    value.update(changes)
    return value


def sample_record(record_id="rec_one", **changes):
    raw = sample_draft()
    result = {"schema_version": 1, "record_id": record_id, "recorded_at": "2026-11-12T20:30:00+08:00"}
    result.update({k: raw[k] for k in CONTENT_KEYS})
    result.update(changes)
    return result


def sample_project():
    return {"schema_version": 1, "project_id": "proj_demo", "public_name": "测试项目", "category": "research", "aliases": []}


def source_page(scan_id="scan_one", turn_id="turn_one", message="完成设计", **changes):
    item = {"item_id": "item_one", "text": message, "sha256": sha(message.encode())}
    ref = {"source_id": "synthetic-session", "turn_id": turn_id, "item_ids": ["item_one"], "unit_id": "unit_one",
           "content_sha256": fingerprint([{"item_id": "item_one", "sha256": item["sha256"]}])}
    d = sample_draft("draft_" + turn_id, source=ref)
    result = {"schema_version": 1, "source_id": ref["source_id"], "host_id": "local", "scan_id": scan_id,
              "window": {"since": "2026-11-01T00:00:00+08:00", "until": "2026-11-13T00:00:00+08:00"},
              "cursor": None, "next_cursor": None, "has_more": False, "anchor_reached": False,
              "turns": [{"turn_id": turn_id, "started_at": "2026-11-12T12:00:00+08:00", "status": "completed",
                         "items": [item], "outcome": "generated", "reason": "已确认测试工作", "drafts": [d]}]}
    result.update(changes)
    return result


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="progress-test-")
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        shutil.copytree(ROOT / "src", self.repo / "src")
        (self.repo / "public").mkdir()
        atomic_json(self.repo / "public/projects.json", {"schema_version": 1, "projects": []})
        self.ctx = Context(self.repo, self.root / "private")

    def tearDown(self):
        self.temp.cleanup()

    def install_public(self, projects, records):
        for path in (self.repo / "public").rglob("*.json"):
            path.unlink()
        for path, data in public_files(projects, records).items():
            atomic_bytes(self.repo / path, data)

    def add_project(self):
        return project_change(self.ctx, "create", "proj_demo", "测试项目", "research")["draft_id"]

    def batch(self):
        p = self.add_project()
        d = import_draft(self.ctx, sample_draft())["draft_id"]
        return preview(self.ctx, [p, d])

    def test_manual_duplicate_stable_id_and_timestamp(self):
        first = import_draft(self.ctx, sample_draft())
        before = copy.deepcopy(catalog(self.ctx))
        second = import_draft(self.ctx, sample_draft())
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["record_id"], second["record_id"])
        self.assertEqual(before, catalog(self.ctx))
        self.assertEqual(load_public(self.repo), ([], []))

    def test_source_duplicate_new_agent_draft_id(self):
        d = source_page()["turns"][0]["drafts"][0]
        first = import_draft(self.ctx, d)
        d["draft_id"] = "agent_regenerated_id"
        second = import_draft(self.ctx, d)
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["record_id"], second["record_id"])

    def test_source_changes_and_new_splits_require_review(self):
        d = source_page()["turns"][0]["drafts"][0]
        first = import_draft(self.ctx, d)
        d["summary"] = "完成修订设计"
        result = import_draft(self.ctx, d)
        self.assertEqual(result["record_id"], first["record_id"])
        self.assertTrue(result["needs_review"])
        confirm_draft(self.ctx, result["draft_id"], result["review_digest"])
        self.assertFalse(catalog(self.ctx)["drafts"][result["draft_id"]]["needs_review"])
        d["source"]["unit_id"] = "new_split"
        d["draft_id"] = "new_split_id"
        self.assertTrue(import_draft(self.ctx, d)["needs_review"])

    def test_agent_cannot_set_recorded_at_or_unknown_fields(self):
        for key, value in [("recorded_at", now()), ("record_id", "rec_injected"), ("private_extra", "x")]:
            with self.subTest(key=key), self.assertRaises(Error):
                import_draft(self.ctx, sample_draft(**{key: value}))

    def test_snapshot_pair_and_status(self):
        for changes in [{"state_as_of": None}, {"state_snapshot": None},
                        {"state_snapshot": {"status": "unknown", "next_step": None, "blocker": None}},
                        {"record_type": "state_update", "state_snapshot": None, "state_as_of": None}]:
            with self.subTest(changes=changes), self.assertRaises(Error):
                record(sample_record(**changes))
        record(sample_record(state_as_of=None, state_snapshot=None))

    def test_time_intervals_and_midnight_boundaries(self):
        self.assertTrue(overlaps("2026-11-12", "2026-11-12T18:00:00+08:00"))
        self.assertFalse(overlaps("2026-11-12", "2026-11-13T00:00:00+08:00"))
        self.assertTrue(before("2026-11-12", "2026-11-13T00:00:00+08:00"))
        self.assertFalse(before("2026-11-12", "2026-11-12T18:00:00+08:00"))
        self.assertEqual(bucket(sample_record(occurred_at="2026-11-12T20:00:00Z")), "public/records/2026/11/13.json")

    def test_conflicting_overlapping_snapshots(self):
        a = sample_record()
        b = sample_record("rec_two", state_as_of="2026-11-12T18:00:00+08:00",
                          state_snapshot={"status": "blocked", "next_step": None, "blocker": "等待结果"})
        with self.assertRaisesRegex(Error, "overlapping"):
            dataset([sample_project()], [a, b])
        b["state_snapshot"] = a["state_snapshot"]
        dataset([sample_project()], [a, b])

    def test_null_snapshots_and_progress_separate(self):
        progress = sample_record()
        blocked = sample_record("rec_blocked", record_type="state_update", occurred_at="2026-11-13",
                                state_as_of="2026-11-13", summary="等待外部结果",
                                state_snapshot={"status": "blocked", "next_step": None, "blocker": "等待外部结果"})
        historical = sample_record("rec_history", occurred_at="2026-11-10", state_as_of=None, state_snapshot=None,
                                   recorded_at="2026-11-14T12:00:00+08:00")
        card = presentation([sample_project()], [historical, blocked, progress])["projects"][0]
        self.assertEqual(card["state_snapshot"]["status"], "blocked")
        self.assertEqual([r["record_id"] for r in card["latest_progress"]], ["rec_one"])

    def test_mixed_precision_latest_is_not_fake_order(self):
        records = [sample_record("rec_date", state_as_of=None, state_snapshot=None),
                   sample_record("rec_morning", occurred_at="2026-11-12T09:30:00+08:00", state_as_of=None, state_snapshot=None),
                   sample_record("rec_evening", occurred_at="2026-11-12T18:00:00+08:00", state_as_of=None, state_snapshot=None)]
        data = presentation([sample_project()], records)
        self.assertEqual({r["record_id"] for r in data["projects"][0]["latest_progress"]}, {"rec_date", "rec_evening"})
        self.assertEqual(data, presentation([sample_project()], list(reversed(records))))
        self.assertEqual(data["timeline"][0]["untimed"][0]["occurred_at"], "2026-11-12")

    def test_cross_date_revision_moves_and_deletes(self):
        old = sample_record(occurred_at="2026-11-10", state_as_of=None, state_snapshot=None)
        self.install_public([sample_project()], [old])
        revision = {"target_record_id": "rec_one", "correct_occurred_at": True, "correct_state_as_of": False}
        d = sample_draft(occurred_at="2026-11-12", state_as_of=None, state_snapshot=None, revision=revision)
        draft_id = import_draft(self.ctx, d)["draft_id"]
        batch = preview(self.ctx, [draft_id])
        operations = {o["path"]: o["action"] for o in batch["operations"]}
        self.assertEqual(operations, {"public/records/2026/11/10.json": "delete", "public/records/2026/11/12.json": "add"})
        directory, _, _ = verify_batch(self.ctx, batch["batch_id"])
        records = load_public(directory / "candidate")[1]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["recorded_at"], old["recorded_at"])
        self.assertEqual(load_public(self.repo)[1][0], old)

    def test_revision_requires_flags_and_immutable_project(self):
        self.install_public([sample_project()], [sample_record()])
        revision = {"target_record_id": "rec_one", "correct_occurred_at": False, "correct_state_as_of": False}
        for changes in [{"occurred_at": "2026-11-10"}, {"state_as_of": "2026-11-10"}, {"project_id": "proj_other"}]:
            with self.subTest(changes=changes), self.assertRaises(Error):
                import_draft(self.ctx, sample_draft(revision=revision, **changes))

    def test_global_duplicates_and_wrong_bucket(self):
        with self.assertRaisesRegex(Error, "duplicate global"):
            dataset([sample_project()], [sample_record(), sample_record()])
        self.install_public([sample_project()], [sample_record()])
        source = self.repo / "public/records/2026/11/12.json"
        source.rename(source.with_name("13.json"))
        with self.assertRaisesRegex(Error, "wrong date"):
            load_public(self.repo)

    def test_project_rename_preserves_identity(self):
        self.install_public([sample_project()], [sample_record()])
        result = project_change(self.ctx, "rename", "proj_demo", "新的公开名称")
        b = preview(self.ctx, [result["draft_id"]])
        directory, _, _ = verify_batch(self.ctx, b["batch_id"])
        projects, records = load_public(directory / "candidate")
        self.assertEqual(projects[0]["aliases"], ["测试项目"])
        self.assertEqual(records[0]["project_id"], projects[0]["project_id"])
        self.assertEqual(load_public(self.repo)[0][0]["public_name"], "测试项目")

    def test_canonical_and_manifest_hash(self):
        self.assertEqual(canonical({"b": 2, "a": "中"}), canonical({"a": "中", "b": 2}))
        self.assertEqual(canonical({"b": 2, "a": "中"}), '{"a":"中","b":2}\n'.encode())
        with self.assertRaises(ValueError): canonical({"x": float("nan")})
        b = self.batch()
        directory, manifest, digest = verify_batch(self.ctx, b["batch_id"])
        self.assertEqual(digest, sha((directory / "manifest.json").read_bytes()))
        self.assertEqual(digest, b["digest"])

    def test_candidate_and_preview_tamper_blocks_approval(self):
        b = self.batch()
        directory, _, _ = verify_batch(self.ctx, b["batch_id"])
        file = directory / "candidate/public/projects.json"
        original = file.read_bytes()
        file.write_bytes(original + b" ")
        with self.assertRaises(Error): approve(self.ctx, b["batch_id"], b["digest"])
        file.write_bytes(original)
        (directory / "preview.md").write_text("changed")
        with self.assertRaises(Error): approve(self.ctx, b["batch_id"], b["digest"])

    def test_manifest_tamper_and_baseline_changes(self):
        b = self.batch()
        directory, _, _ = verify_batch(self.ctx, b["batch_id"])
        file = directory / "manifest.json"
        value = read_json(file)
        value["created_at"] = "2026-11-01T00:00:00+08:00"
        atomic_json(file, value)
        with self.assertRaises(Error): verify_batch(self.ctx, b["batch_id"])
        b = self.batch()
        self.install_public([sample_project()], [])
        with self.assertRaises(Error): verify_batch(self.ctx, b["batch_id"])

    def test_git_head_change_invalidates_batch(self):
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        b = self.batch()
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "--allow-empty", "-qm", "initial"], check=True)
        with self.assertRaisesRegex(Error, "Git baseline"):
            verify_batch(self.ctx, b["batch_id"])

    def test_approval_only_local_and_no_publish(self):
        b = self.batch()
        result = approve(self.ctx, b["batch_id"], b["digest"])
        self.assertFalse(result["published"])
        self.assertEqual(load_public(self.repo), ([], []))

    def test_privacy_detects_without_echoing_secret(self):
        for phrase in ["写入 a@example.com", "保存 /Users/demo/private.txt", "查看 https://internal.invalid/x",
                       "令牌 ghp_abcdefghijk", "电话 13812345678", "联系 +1 415-555-0123",
                       "会话 12345678-abcd-abcd-abcd-123456789abc", "密钥 token=abcdefghijkl"]:
            with self.subTest(phrase=phrase), self.assertRaises(Error) as caught:
                dataset([sample_project()], [sample_record(summary=phrase)])
            self.assertNotIn(phrase, str(caught.exception))

    def test_path_allowlist_and_symlink_guards(self):
        for path in ["../private/a.json", "/private/a.json", "public/../../a.json", "public/records/2026/99/12.json", "public/a.json"]:
            with self.subTest(path=path), self.assertRaises(Error): public_path(self.repo, path)
        (self.repo / "public/link").symlink_to(self.ctx.local, target_is_directory=True)
        with self.assertRaises(Error): load_public(self.repo)

    def test_local_roots_cannot_overlap_or_be_git_tracked(self):
        with self.assertRaises(Error): Context(self.repo, self.repo / "private")
        with self.assertRaises(Error): Context(self.repo, self.root)
        parent = self.root / "tracked"
        parent.mkdir()
        (parent / ".git").mkdir()
        with self.assertRaises(Error): Context(self.repo, parent / "private")

    def test_build_empty_and_candidate_no_private_leak(self):
        result = build(self.ctx)
        data = read_json(Path(result["output"]) / "data.json")
        self.assertEqual(data["projects"], [])
        b = self.batch()
        out = self.root / "preview"
        build(self.ctx, out, b["batch_id"])
        self.assertEqual(set(p.name for p in out.iterdir()), {"index.html", "styles.css", "app.js", "data.json", "build.json"})
        payload = (out / "data.json").read_text()
        self.assertNotIn('"evidence":', payload)
        self.assertNotIn("draft_id", payload)
        self.assertNotIn("source_id", payload)
        self.assertEqual(load_public(self.repo), ([], []))
        with self.assertRaises(Error): build(self.ctx, self.repo / "dist", b["batch_id"])

    def test_build_symlink_and_foreign_output_refused(self):
        out = self.root / "output"
        out.mkdir()
        (out / "index.html").symlink_to(self.ctx.local / "private.txt")
        with self.assertRaises(Error): build(self.ctx, out)
        (out / "index.html").unlink()
        (out / "foreign.txt").write_text("keep")
        with self.assertRaises(Error): build(self.ctx, out)

    def test_json_duplicates_and_nan_rejected(self):
        p = self.root / "bad.json"
        for raw in ['{"a":1,"a":2}', '{"a":NaN}']:
            p.write_text(raw)
            with self.assertRaises(Error): read_json(p)

    def test_capture_complete_and_duplicate_replay(self):
        page = source_page()
        first = capture(self.ctx, page)
        second = capture(self.ctx, page)
        self.assertEqual(first["status"], "complete")
        self.assertEqual(first["checkpoint"], second["checkpoint"])
        self.assertEqual(len(catalog(self.ctx)["drafts"]), 1)

    def test_capture_before_save_and_after_save_crash(self):
        page = source_page()
        with self.assertRaises(RuntimeError): capture(self.ctx, page, "before_save")
        self.assertFalse(list((self.ctx.local / "checkpoints").glob("*.json")))
        with self.assertRaises(RuntimeError): capture(self.ctx, page, "after_save")
        self.assertFalse(list((self.ctx.local / "checkpoints").glob("*.json")))
        before = catalog(self.ctx)["drafts"]["draft_turn_one"]["candidate"]["record_id"]
        capture(self.ctx, page)
        self.assertEqual(before, catalog(self.ctx)["drafts"]["draft_turn_one"]["candidate"]["record_id"])

    def test_capture_partial_cannot_advance_watermark(self):
        page = source_page(has_more=True, next_cursor="older")
        result = capture(self.ctx, page)
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["checkpoint"]["completed_through"])
        wrong = source_page(turn_id="turn_older", cursor="wrong")
        with self.assertRaises(Error): capture(self.ctx, wrong)
        older = source_page(turn_id="turn_older", cursor="older")
        older["turns"][0]["started_at"] = "2026-11-10T12:00:00+08:00"
        result = capture(self.ctx, older)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["checkpoint"]["completed_through"], "turn_one")
        self.assertEqual(capture(self.ctx, page)["checkpoint"], result["checkpoint"])
        self.assertEqual(capture(self.ctx, page)["status"], "complete")

    def test_old_scan_replay_does_not_undo_new_source_revision(self):
        old = source_page()
        capture(self.ctx, old)
        new = source_page(scan_id="scan_new", message="更新证据")
        new["turns"][0]["drafts"][0]["summary"] = "修正后的真实进展"
        capture(self.ctx, new)
        before = catalog(self.ctx)
        result = capture(self.ctx, old)
        self.assertTrue(result["replayed"])
        self.assertEqual(before, catalog(self.ctx))

    def test_50_turn_limit_and_running_turn(self):
        page = source_page()
        page["turns"] = [source_page(turn_id=f"turn_{i}")["turns"][0] for i in range(51)]
        with self.assertRaises(Error): capture(self.ctx, page)
        page["turns"] = page["turns"][:50]
        page["has_more"], page["next_cursor"] = True, "more"
        self.assertEqual(capture(self.ctx, page)["status"], "incomplete")

    def test_unfinished_turn_does_not_advance(self):
        page = source_page()
        page["turns"][0].update(status="in_progress", outcome="needs_review", drafts=[])
        result = capture(self.ctx, page)
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["checkpoint"]["completed_through"])

    def test_changed_message_and_added_item_not_discarded(self):
        capture(self.ctx, source_page())
        page = source_page(scan_id="scan_two", message="修正此前结论")
        result = capture(self.ctx, page)
        self.assertTrue(result["processed"][0]["content_changed"])
        self.assertTrue(result["imports"][0]["needs_review"])
        page = source_page(scan_id="scan_three", message="修正此前结论")
        page["turns"][0]["items"].append({"item_id": "item_two", "text": "补充", "sha256": sha("补充".encode())})
        self.assertTrue(capture(self.ctx, page)["processed"][0]["content_changed"])

    def test_source_hash_and_wrong_evidence_rejected(self):
        page = source_page()
        page["turns"][0]["items"][0]["text"] = "tampered"
        with self.assertRaises(Error): capture(self.ctx, page)

    def test_crash_between_scan_and_checkpoint_recovers(self):
        from unittest.mock import patch
        from dashboard import sources
        original = sources.atomic_json
        def fail_checkpoint(path, data):
            if Path(path).parent.name == "checkpoints":
                raise OSError("injected checkpoint write failure")
            return original(path, data)
        with patch.object(sources, "atomic_json", side_effect=fail_checkpoint):
            with self.assertRaises(OSError): capture(self.ctx, source_page())
        result = capture(self.ctx, source_page())
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(catalog(self.ctx)["drafts"]), 1)

    def test_desktop_adapter_does_not_retain_reasoning_or_outputs(self):
        from dashboard.desktop import normalize
        response = {"thread": {"id": "synthetic-session", "kind": "codex", "hostId": "local"},
                    "page": {"nextCursor": None, "hasMore": False}, "turns": [
                        {"id": "turn_one", "startedAt": 1794480000, "status": "completed", "items": [
                            {"id": "visible", "type": "agentMessage", "text": "已完成本地校验"},
                            {"id": "hidden", "type": "reasoning", "text": "must not retain"},
                            {"id": "tool", "type": "commandExecution", "text": "private output"}]}]}
        result = normalize(response, "scan_one", "2026-11-01T00:00:00+08:00", "2026-11-14T00:00:00+08:00")
        self.assertEqual([i["item_id"] for i in result["turns"][0]["items"]], ["visible"])
        self.assertEqual(result["turns"][0]["outcome"], "needs_review")

    def test_reviewed_draft_tamper_rejected(self):
        p = self.add_project()
        d = import_draft(self.ctx, sample_draft())["draft_id"]
        state = catalog(self.ctx)
        state["drafts"][d]["candidate"]["summary"] = "changed after import"
        save_catalog(self.ctx, state)
        with self.assertRaises(Error): preview(self.ctx, [p, d])

    def test_schema_files_describe_separate_contracts(self):
        schemas = {p.stem: read_json(p) for p in (ROOT / "schemas").glob("*.json")}
        self.assertEqual(len(schemas), 5)
        for schema in schemas.values(): self.assertFalse(schema["additionalProperties"])
        self.assertNotIn("recorded_at", schemas["draft-v1.schema"]["properties"])
        self.assertNotIn("source", schemas["public-record-v1.schema"]["properties"])

    def test_cli_new_process_import_and_empty_build(self):
        input_file = self.root / "input.json"
        atomic_json(input_file, sample_draft())
        import sys
        args = [sys.executable, str(ROOT / "scripts/import.py"), "--repo", str(self.repo), "--local-root", str(self.ctx.local), "--input", str(input_file)]
        one = json.loads(subprocess.check_output(args))
        two = json.loads(subprocess.check_output(args))
        self.assertEqual(one["record_id"], two["record_id"])
        self.assertTrue(two["duplicate"])


if __name__ == "__main__":
    unittest.main()
