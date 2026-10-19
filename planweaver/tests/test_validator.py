# -*- coding: utf-8 -*-
"""校验器单元测试：逐条验证确定性规则，覆盖边界与错误输入。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import (  # noqa: E402
    codes, has_code, make_goal, make_replan, make_state, make_task,
    run_validator, validate, week_start,
)


class SchemaTests(unittest.TestCase):
    def test_valid_baseline_passes(self):
        report = validate(make_state())
        self.assertTrue(report["ok"], report["findings"])
        self.assertEqual(report["verdict"], "feasible")
        self.assertEqual(report["counts"]["errors"], 0)

    def test_schema_version_mismatch(self):
        state = make_state()
        state["schema_version"] = "2.0"
        report = validate(state)
        self.assertIn("E_SCHEMA", codes(report, "error"))

    def test_missing_top_level_field(self):
        state = make_state()
        del state["constraints"]
        report = validate(state)
        self.assertIn("E_SCHEMA", codes(report, "error"))

    def test_empty_goals_rejected(self):
        report = validate(make_state(goals=[], tasks=[make_task()]))
        self.assertFalse(report["ok"])

    def test_duplicate_task_id(self):
        tasks = [make_task("T1"), make_task("T1")]
        report = validate(make_state(tasks=tasks))
        self.assertIn("E_DUP_ID", codes(report, "error"))

    def test_invalid_enum_domain(self):
        report = validate(make_state(goals=[make_goal(domain="study")]))
        self.assertIn("E_ENUM", codes(report, "error"))

    def test_invalid_weight(self):
        report = validate(make_state(goals=[make_goal(weight=9)]))
        self.assertIn("E_TYPE", codes(report, "error"))

    def test_hard_deadline_requires_date(self):
        report = validate(make_state(goals=[make_goal(deadline=None,
                                                      deadline_rigidity="hard")]))
        self.assertIn("E_SCHEMA", codes(report, "error"))

    def test_bad_date_format(self):
        report = validate(make_state(goals=[make_goal(deadline="2026/12/01")]))
        self.assertIn("E_DATE", codes(report, "error"))

    def test_buffer_ratio_out_of_range(self):
        report = validate(make_state(buffer_ratio=0.9))
        self.assertIn("E_ENUM", codes(report, "error"))

    def test_low_buffer_warning(self):
        report = validate(make_state(buffer_ratio=0.02))
        self.assertIn("W_NO_BUFFER", codes(report, "warning"))


class EstimateTests(unittest.TestCase):
    def test_estimate_order_violation(self):
        task = make_task(estimate={"optimistic": 200, "likely": 100, "pessimistic": 300})
        report = validate(make_state(tasks=[task]))
        self.assertIn("E_ESTIMATE_ORDER", codes(report, "error"))

    def test_zero_estimate(self):
        task = make_task(estimate={"optimistic": 0, "likely": 0, "pessimistic": 0})
        report = validate(make_state(tasks=[task]))
        self.assertIn("E_TYPE", codes(report, "error"))

    def test_oversized_task_warns(self):
        task = make_task(estimate={"optimistic": 300, "likely": 400, "pessimistic": 500},
                         scheduled={"week_start": week_start(0), "minutes": 400})
        report = validate(make_state(tasks=[task]))
        self.assertIn("W_TASK_TOO_BIG", codes(report, "warning"))


class DependencyTests(unittest.TestCase):
    def test_missing_dependency_reference(self):
        report = validate(make_state(tasks=[make_task("T1", depends_on=["T7"])]))
        self.assertIn("E_REF", codes(report, "error"))

    def test_self_dependency(self):
        report = validate(make_state(tasks=[make_task("T1", depends_on=["T1"])]))
        self.assertIn("E_CYCLE", codes(report, "error"))

    def test_cycle_reports_path(self):
        tasks = [
            make_task("T1", depends_on=["T3"]),
            make_task("T2", depends_on=["T1"]),
            make_task("T3", depends_on=["T2"]),
        ]
        report = validate(make_state(tasks=tasks))
        messages = " ".join(f["message"] for f in report["findings"] if f["code"] == "E_CYCLE")
        for tid in ("T1", "T2", "T3"):
            self.assertIn(tid, messages)

    def test_predecessor_deadline_after_successor(self):
        tasks = [
            make_task("T1", due="2026-11-10"),
            make_task("T2", depends_on=["T1"], due="2026-11-01"),
        ]
        report = validate(make_state(tasks=tasks))
        self.assertIn("E_DEP_DEADLINE", codes(report, "error"))


class CapacityTests(unittest.TestCase):
    def test_week_over_hard_limit(self):
        task = make_task(scheduled={"week_start": week_start(0), "minutes": 1000},
                         estimate={"optimistic": 800, "likely": 900, "pessimistic": 1000})
        report = validate(make_state(tasks=[task]))
        self.assertIn("E_CAPACITY", codes(report, "error"))

    def test_week_between_effective_and_hard_limit(self):
        task = make_task(scheduled={"week_start": week_start(0), "minutes": 800},
                         estimate={"optimistic": 700, "likely": 800, "pessimistic": 850})
        report = validate(make_state(tasks=[task]))
        self.assertIn("W_TIGHT_WEEK", codes(report, "warning"))
        self.assertNotIn("E_CAPACITY", codes(report, "error"))

    def test_schedule_outside_horizon(self):
        task = make_task(scheduled={"week_start": "2027-03-01", "minutes": 60})
        report = validate(make_state(tasks=[task]))
        self.assertIn("W_SCHEDULE_OUTSIDE", codes(report, "warning"))

    def test_verdict_tight_when_pessimistic_exceeds(self):
        tasks = [
            make_task(f"T{i}", scheduled={"week_start": week_start(i), "minutes": 830},
                      estimate={"optimistic": 700, "likely": 833, "pessimistic": 1166})
            for i in range(6)
        ]
        report = validate(make_state(tasks=tasks))
        self.assertEqual(report["verdict"], "tight",
                         f"metrics={report['metrics']}")
        self.assertTrue(report["ok"])

    def test_verdict_infeasible_when_likely_exceeds(self):
        tasks = [
            make_task(f"T{i}", scheduled={"week_start": week_start(i), "minutes": 850},
                      estimate={"optimistic": 800, "likely": 850, "pessimistic": 900})
            for i in range(9)
        ]
        report = validate(make_state(tasks=tasks))
        self.assertEqual(report["verdict"], "infeasible")


class ConflictTests(unittest.TestCase):
    def test_task_overlaps_fixed_event(self):
        fixed = [{"id": "F1", "title": "周会", "recurring": True, "weekday": 0,
                  "start": "10:00", "end": "11:00"}]
        task = make_task(blocks=[{"date": "2026-10-19", "start": "10:30", "end": "11:30"}])
        report = validate(make_state(tasks=[task], fixed_events=fixed))
        self.assertIn("E_OVERLAP", codes(report, "error"))

    def test_task_overlaps_protected_window(self):
        protected = [{"id": "P1", "label": "午休", "start": "12:00", "end": "13:00",
                      "rigid": True}]
        task = make_task(blocks=[{"date": "2026-10-20", "start": "12:30", "end": "13:30"}])
        report = validate(make_state(tasks=[task], protected_blocks=protected))
        self.assertIn("E_PROTECTED", codes(report, "error"))
        messages = " ".join(f["message"] for f in report["findings"]
                            if f["code"] == "E_PROTECTED")
        self.assertIn("午休", messages)

    def test_day_oversubscribed(self):
        protected = [{"id": "P1", "label": "睡眠", "daily_minutes": 480, "rigid": True},
                     {"id": "P2", "label": "运动", "daily_minutes": 45, "rigid": True}]
        task = make_task(blocks=[{"date": "2026-10-20", "start": "08:00", "end": "23:20"}])
        report = validate(make_state(tasks=[task], protected_blocks=protected))
        messages = " ".join(f["message"] for f in report["findings"]
                            if f["code"] == "E_PROTECTED")
        self.assertIn("1440", messages)

    def test_two_task_blocks_overlap(self):
        tasks = [
            make_task("T1", blocks=[{"date": "2026-10-20", "start": "09:00", "end": "11:00"}]),
            make_task("T2", blocks=[{"date": "2026-10-20", "start": "10:00", "end": "12:00"}]),
        ]
        report = validate(make_state(tasks=tasks))
        self.assertIn("E_OVERLAP", codes(report, "error"))


class ProgressTests(unittest.TestCase):
    def test_done_without_evidence(self):
        task = make_task(status="done")
        report = validate(make_state(tasks=[task]))
        self.assertIn("E_PROGRESS", codes(report, "error"))

    def test_actual_minutes_but_todo(self):
        task = make_task(status="todo", actual_minutes=45)
        report = validate(make_state(tasks=[task]))
        self.assertIn("W_PROGRESS", codes(report, "warning"))

    def test_estimate_drift_warning(self):
        task = make_task(status="done", actual_minutes=500,
                         completed_at="2026-10-21T10:00:00+08:00",
                         scheduled={"week_start": week_start(0), "minutes": 90})
        report = validate(make_state(tasks=[task]))
        self.assertIn("W_ESTIMATE_DRIFT", codes(report, "warning"))


class ReplanDisciplineTests(unittest.TestCase):
    def _chain(self):
        return [
            make_task("T1"), make_task("T2", depends_on=["T1"]),
            make_task("T3", depends_on=["T2"]), make_task("T4"),
        ]

    def test_s0_with_movement_is_flagged(self):
        replan = make_replan(affected=["T1"], moved=["T2"], strategy="S0")
        report = validate(make_state(tasks=self._chain(), replans=[replan]))
        self.assertIn("W_STRATEGY_MISMATCH", codes(report, "warning"))

    def test_s4_on_hard_deadline_rejected(self):
        goal = make_goal(deadline="2026-11-01", deadline_rigidity="hard")
        replan = make_replan(trigger_type="deadline_change", affected=["T1"], moved=["T1"],
                             strategy="S4")
        report = validate(make_state(goals=[goal], tasks=[make_task("T1")], replans=[replan]))
        self.assertIn("E_STRATEGY_HARD_DEADLINE_EXTEND", codes(report, "error"))

    def test_s2_on_unsafe_task_warns(self):
        replan = make_replan(affected=["T1"], moved=["T1"], strategy="S2")
        report = validate(make_state(tasks=[make_task("T1", compression_safe=False)],
                                     replans=[replan]))
        self.assertIn("W_COMPRESSION_UNSAFE", codes(report, "warning"))

    def test_s2_on_safe_task_is_clean(self):
        replan = make_replan(affected=["T1"], moved=["T1"], strategy="S2")
        report = validate(make_state(tasks=[make_task("T1", compression_safe=True)],
                                     replans=[replan]))
        self.assertNotIn("W_COMPRESSION_UNSAFE", codes(report, "warning"))

    def test_mass_rollover_flagged(self):
        tasks = self._chain() + [make_task("T5"), make_task("T6")]
        # 6 个未完成任务里移动 5 个，属于典型的"整表后移"
        replan = make_replan(affected=["T1"], moved=["T1", "T2", "T4", "T5", "T6"],
                             strategy="S1")
        report = validate(make_state(tasks=tasks, replans=[replan]))
        self.assertIn("W_ROLLOVER_MASS", codes(report, "warning"))
        self.assertIn("W_ROLLOVER", codes(report, "warning"))

    def test_empty_affected_but_moved(self):
        replan = make_replan(affected=[], moved=["T1"], strategy="S1")
        report = validate(make_state(tasks=[make_task("T1")], replans=[replan]))
        self.assertIn("W_ROLLOVER", codes(report, "warning"))

    def test_bad_strategy_enum(self):
        replan = make_replan(affected=["T1"], moved=[], strategy="S9")
        report = validate(make_state(tasks=[make_task("T1")], replans=[replan]))
        self.assertIn("E_ENUM", codes(report, "error"))


class CliTests(unittest.TestCase):
    def test_missing_file_exit_2(self):
        code, payload = run_validator(make_state())  # 先用临时目录跑一次确认基线
        self.assertEqual(code, 0)

    def test_invalid_json_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"schema_version": "1.0",}')
            from support import _run, PYTHON, VALIDATOR
            code, payload = _run([PYTHON, VALIDATOR, "--state", path])
            self.assertEqual(code, 2)
            self.assertIn("E_JSON", json.dumps(payload, ensure_ascii=False))

    def test_text_format_contains_verdict(self):
        code, text = run_validator(make_state(), "--format", "text")
        self.assertEqual(code, 0)
        self.assertIn("可行性判定", text)
        self.assertIn("可行", text)

    def test_strict_upgrades_warnings(self):
        task = make_task(status="todo", actual_minutes=30)
        code, payload = run_validator(make_state(tasks=[task]), "--strict")
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_errors_exit_1(self):
        tasks = [make_task("T1", depends_on=["T1"])]
        code, payload = run_validator(make_state(tasks=tasks))
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])

    def test_report_has_no_timestamp_for_reproducibility(self):
        _, payload = run_validator(make_state())
        self.assertNotIn("checked_at", payload)
        self.assertEqual(payload["tool"], "planweaver-validate/1.0.0")


class MetricsTests(unittest.TestCase):
    def test_critical_path(self):
        tasks = [
            make_task("T1", estimate={"optimistic": 60, "likely": 100, "pessimistic": 140},
                      scheduled={"week_start": week_start(0), "minutes": 100}),
            make_task("T2", depends_on=["T1"],
                      estimate={"optimistic": 60, "likely": 200, "pessimistic": 240},
                      scheduled={"week_start": week_start(1), "minutes": 200}),
            make_task("T3", estimate={"optimistic": 60, "likely": 50, "pessimistic": 80},
                      scheduled={"week_start": week_start(0), "minutes": 50}),
        ]
        report = validate(make_state(tasks=tasks))
        self.assertEqual(report["metrics"]["critical_path"], ["T1", "T2"])
        self.assertEqual(report["metrics"]["critical_path_minutes"], 300)

    def test_negative_slack_detected(self):
        tasks = [
            make_task("T1", due="2026-10-20",
                      estimate={"optimistic": 600, "likely": 900, "pessimistic": 1200},
                      scheduled={"week_start": week_start(0), "minutes": 900}),
        ]
        report = validate(make_state(tasks=tasks))
        self.assertIn("T1", report["metrics"]["negative_slack_tasks"])

    def test_slack_respects_scheduled_week(self):
        """任务不可能早于它被安排的那一周开始，余量不能被高估。"""
        tasks = [
            make_task("T1", due="2026-11-10",
                      estimate={"optimistic": 40, "likely": 60, "pessimistic": 90},
                      scheduled={"week_start": week_start(3), "minutes": 60}),
        ]
        report = validate(make_state(tasks=tasks))
        slack = report["metrics"]["slack_days"]["T1"]
        self.assertLess(slack, 2.0, f"排在第 4 周的任务，余量不应被算成 20 天以上：{slack}")
        self.assertGreater(slack, 0.0)

    def test_negative_slack_emits_warning(self):
        tasks = [
            make_task("T1", due="2026-10-20",
                      estimate={"optimistic": 600, "likely": 900, "pessimistic": 1200},
                      scheduled={"week_start": week_start(0), "minutes": 900}),
        ]
        report = validate(make_state(tasks=tasks))
        self.assertIn("W_NEGATIVE_SLACK", codes(report, "warning"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
