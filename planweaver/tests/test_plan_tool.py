# -*- coding: utf-8 -*-
"""plan_tool.py 的 CLI 集成测试：建档、更新、重规划、导出、数据保全。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import TOOL, run_tool  # noqa: E402

INIT_ARGS = ["--horizon-start", "2026-10-19", "--weeks", "8",
             "--weekly-minutes", "900", "--title", "集成测试计划"]


def load(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class InitTests(unittest.TestCase):
    def test_init_creates_three_files_and_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "plan")
            code, _ = run_tool("init", "--out", out, *INIT_ARGS)
            self.assertEqual(code, 0)
            for name in ("plan-state.json", "plan-overview.md", "change-log.md"):
                self.assertTrue(os.path.isfile(os.path.join(out, name)), name)

            state = load(os.path.join(out, "plan-state.json"))
            self.assertEqual(state["meta"]["horizon_start"], "2026-10-19")
            self.assertEqual(state["meta"]["horizon_end"], "2026-12-13")
            self.assertEqual(state["meta"]["revision"], 1)
            self.assertEqual(state["constraints"]["capacity"]["weekly_minutes"], 900)

            code, payload = run_tool("validate", "--state",
                                     os.path.join(out, "plan-state.json"))
            self.assertEqual(code, 0)

            overview = open(os.path.join(out, "plan-overview.md"), encoding="utf-8").read()
            self.assertIn("集成测试计划", overview)
            self.assertNotIn("{{", overview, "占位符必须被替换")

    def test_init_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "plan")
            run_tool("init", "--out", out, *INIT_ARGS)
            code, text = run_tool("init", "--out", out, *INIT_ARGS)
            self.assertEqual(code, 2)
            self.assertIn("已存在", str(text))

    def test_init_force_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "plan")
            run_tool("init", "--out", out, *INIT_ARGS)
            code, _ = run_tool("init", "--out", out, *INIT_ARGS, "--force")
            self.assertEqual(code, 0)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "plan")
        run_tool("init", "--out", self.out, *INIT_ARGS)
        self.state_path = os.path.join(self.out, "plan-state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_records_progress_and_bumps_revision(self):
        code, _ = run_tool("update", "--state", self.state_path, "--task", "T1",
                           "--status", "done", "--actual", "150", "--note", "口径返工")
        self.assertEqual(code, 0)
        state = load(self.state_path)
        self.assertEqual(state["meta"]["revision"], 2)
        task = next(t for t in state["tasks"] if t["id"] == "T1")
        self.assertEqual(task["status"], "done")
        self.assertEqual(task["actual_minutes"], 150)
        self.assertIsNotNone(task["completed_at"])
        self.assertEqual(len(state["progress_log"]), 1)
        self.assertEqual(state["progress_log"][0]["event"], "done")

    def test_update_creates_backup(self):
        run_tool("update", "--state", self.state_path, "--task", "T1",
                 "--status", "doing", "--actual", "30")
        backups = os.listdir(os.path.join(self.out, "backups"))
        self.assertTrue(backups, "写入前必须备份")
        self.assertTrue(backups[0].endswith(".json"))

    def test_update_unknown_task_fails(self):
        code, text = run_tool("update", "--state", self.state_path, "--task", "T99",
                              "--status", "done")
        self.assertEqual(code, 2)
        self.assertIn("找不到任务", str(text))

    def test_update_without_changes_fails(self):
        code, text = run_tool("update", "--state", self.state_path, "--task", "T1")
        self.assertEqual(code, 2)
        self.assertIn("没有要修改的内容", str(text))

    def test_add_actual_accumulates(self):
        run_tool("update", "--state", self.state_path, "--task", "T1", "--add-actual", "40")
        run_tool("update", "--state", self.state_path, "--task", "T1", "--add-actual", "35")
        state = load(self.state_path)
        task = next(t for t in state["tasks"] if t["id"] == "T1")
        self.assertEqual(task["actual_minutes"], 75)

    def test_unknown_fields_preserved(self):
        state = load(self.state_path)
        state["custom_extension"] = {"keep": True}
        state["tasks"][0]["my_note"] = "保留我"
        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False)

        run_tool("update", "--state", self.state_path, "--task", "T1",
                 "--status", "doing", "--actual", "20")
        after = load(self.state_path)
        self.assertEqual(after["custom_extension"], {"keep": True})
        self.assertEqual(after["tasks"][0]["my_note"], "保留我")


class ReplanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "plan")
        run_tool("init", "--out", self.out, *INIT_ARGS)
        self.state_path = os.path.join(self.out, "plan-state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_shift_only_moves_listed_tasks(self):
        before = load(self.state_path)
        before_weeks = {t["id"]: t["scheduled"]["week_start"] for t in before["tasks"]}

        code, _ = run_tool("replan", "--state", self.state_path,
                           "--trigger-type", "delay",
                           "--description", "T2 大纲延后 3 天",
                           "--affected", "T2", "--strategy", "S1",
                           "--moved", "T2", "--shift-days", "3",
                           "--approved")
        self.assertEqual(code, 0)

        after = load(self.state_path)
        after_weeks = {t["id"]: t["scheduled"]["week_start"] for t in after["tasks"]}
        self.assertNotEqual(before_weeks["T2"], after_weeks["T2"], "T2 应被平移")
        self.assertEqual(before_weeks["T1"], after_weeks["T1"], "T1 不在移动列表，必须保持原样")
        self.assertEqual(before_weeks["T3"], after_weeks["T3"], "T3 不在移动列表，必须保持原样")

        self.assertEqual(len(after["replans"]), 1)
        record = after["replans"][0]
        self.assertEqual(record["strategy"], "S1")
        self.assertEqual(record["moved_task_ids"], ["T2"])
        self.assertTrue(record["approved_by_user"])

    def test_s4_on_hard_deadline_fails_validation(self):
        state = load(self.state_path)
        state["goals"][0]["deadline_rigidity"] = "hard"
        state["goals"][0]["deadline"] = "2026-11-15"
        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False)

        code, _ = run_tool("replan", "--state", self.state_path,
                           "--trigger-type", "deadline_change",
                           "--description", "把硬截止往后推",
                           "--affected", "T1", "--strategy", "S4",
                           "--moved", "T1", "--approved")
        self.assertEqual(code, 1, "硬截止上使用 S4 必须校验失败")

    def test_bad_trigger_type(self):
        code, text = run_tool("replan", "--state", self.state_path,
                              "--trigger-type", "unknown", "--description", "x",
                              "--strategy", "S1")
        self.assertEqual(code, 2)


class AddTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "plan")
        run_tool("init", "--out", self.out, *INIT_ARGS)
        self.state_path = os.path.join(self.out, "plan-state.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_task_autoid_and_fields(self):
        code, _ = run_tool("add-task", "--state", self.state_path,
                           "--goal", "G1", "--title", "补充竞品对标",
                           "--likely", "90", "--week", "2026-11-02",
                           "--depends", "T3", "--due", "2026-11-06",
                           "--acceptance", "含 3 家竞品,含结论")
        self.assertEqual(code, 0)
        state = load(self.state_path)
        task = state["tasks"][-1]
        self.assertEqual(task["id"], "T4")
        self.assertEqual(task["depends_on"], ["T3"])
        self.assertEqual(task["acceptance_criteria"], ["含 3 家竞品", "含结论"])
        self.assertEqual(task["estimate"]["optimistic"], 90)
        self.assertEqual(task["estimate"]["pessimistic"], 90)

    def test_add_task_bad_estimate_order(self):
        code, text = run_tool("add-task", "--state", self.state_path,
                              "--goal", "G1", "--title", "x", "--likely", "60",
                              "--optimistic", "90", "--pessimistic", "30")
        self.assertEqual(code, 2)
        self.assertIn("optimistic", str(text))

    def test_add_task_unknown_goal(self):
        code, text = run_tool("add-task", "--state", self.state_path,
                              "--goal", "G9", "--title", "x", "--likely", "60")
        self.assertEqual(code, 2)
        self.assertIn("G9", str(text))


class ExportSummaryTests(unittest.TestCase):
    def test_export_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "plan")
            run_tool("init", "--out", out, *INIT_ARGS)
            state_path = os.path.join(out, "plan-state.json")
            export_path = os.path.join(tmp, "export.json")

            code, _ = run_tool("export", "--state", state_path, "--out", export_path)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isfile(export_path))
            self.assertEqual(load(export_path)["plan_id"], load(state_path)["plan_id"])

            code, text = run_tool("summary", "--state", state_path)
            self.assertEqual(code, 0)
            for keyword in ("目标", "任务", "资源", "可行性", "关键路径"):
                self.assertIn(keyword, str(text))


if __name__ == "__main__":
    unittest.main(verbosity=2)
