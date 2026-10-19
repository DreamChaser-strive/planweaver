# -*- coding: utf-8 -*-
"""12 个必测场景。每个用例都对应需求文档里的一条场景，断言可观察的行为。

运行：python tests/run_tests.py
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import (  # noqa: E402
    codes, has_code, make_goal, make_replan, make_state, make_task, validate, week_start,
)
from validate_plan import Validator  # noqa: E402


class ScenarioTests(unittest.TestCase):
    """场景 1–12：覆盖正常路径、边界与错误输入。"""

    # 场景 1 ---------------------------------------------------------------
    def test_01_vague_goal_without_deadline(self):
        """只提出模糊目标、没有截止日期：不报错，但必须提示无期限无法排期。"""
        state = make_state(
            goals=[make_goal(deadline=None, deadline_rigidity="open", weight=3)],
            tasks=[make_task()],
        )
        report = validate(state)
        self.assertTrue(report["ok"], "无期限目标不应阻塞校验")
        self.assertIn("W_GOAL_NO_DEADLINE", codes(report, "warning"),
                      "必须提示目标没有截止日期")
        # 无期限时不应伪造一个期限
        self.assertIsNone(state["goals"][0]["deadline"])

    # 场景 2 ---------------------------------------------------------------
    def test_02_three_domains_share_one_ledger(self):
        """学习+工作+生活三目标：必须汇总到同一本账，而不是三份独立计划。"""
        goals = [
            make_goal("G1", domain="learning", name="雅思 6.5", deadline="2026-12-10"),
            make_goal("G2", domain="work", name="项目一期", deadline="2026-11-15"),
            make_goal("G3", domain="life", name="每周三次运动", deadline=None,
                      deadline_rigidity="open"),
        ]
        tasks = [
            make_task("T1", "G1", scheduled={"week_start": "2026-10-19", "minutes": 240}),
            make_task("T2", "G2", scheduled={"week_start": "2026-10-19", "minutes": 240}),
            make_task("T3", "G3", scheduled={"week_start": "2026-10-19", "minutes": 240}),
        ]
        report = validate(state=make_state(goals=goals, tasks=tasks))
        metrics = report["metrics"]
        self.assertEqual(metrics["tasks_open"], 3)
        self.assertEqual(metrics["effort_likely"], 270, "三个域的工时必须进同一个总量")
        self.assertEqual(metrics["verdict"], "feasible")
        # 同一周合计 720 分钟，未超有效容量 765，不应报超载
        self.assertFalse(has_code(report, "E_CAPACITY"))

    # 场景 3 ---------------------------------------------------------------
    def test_03_total_effort_exceeds_capacity(self):
        """任务总耗时超过可用时间：必须报超载，且判定不可行。"""
        tasks = [
            make_task(f"T{i}", scheduled={"week_start": week_start(i),
                                          "minutes": 1000},
                      estimate={"optimistic": 800, "likely": 1000, "pessimistic": 1200})
            for i in range(6)
        ]
        report = validate(make_state(tasks=tasks))
        self.assertFalse(report["ok"], "超载必须让校验失败")
        self.assertIn("E_CAPACITY", codes(report, "error"))
        self.assertEqual(report["verdict"], "infeasible")
        # 报错信息必须给出具体周与具体数字，而不是泛泛而谈
        message = " ".join(f["message"] for f in report["findings"] if f["code"] == "E_CAPACITY")
        self.assertIn("1000", message)
        self.assertIn("900", message)

    # 场景 4 ---------------------------------------------------------------
    def test_04_fixed_event_conflicts_with_flexible_task(self):
        """固定日程与弹性任务撞车：必须识别为错误，固定安排不可移动。"""
        fixed = [{"id": "F1", "title": "团队周会", "recurring": True, "weekday": 0,
                  "start": "10:00", "end": "11:00", "rigid": True}]
        task = make_task(blocks=[{"date": "2026-10-19", "start": "10:30", "end": "11:30"}])
        report = validate(make_state(tasks=[task], fixed_events=fixed))
        self.assertIn("E_OVERLAP", codes(report, "error"))
        message = " ".join(f["message"] for f in report["findings"] if f["code"] == "E_OVERLAP")
        self.assertIn("团队周会", message)

    # 场景 5 ---------------------------------------------------------------
    def test_05_successor_scheduled_before_predecessor_done(self):
        """前置未完成但后续已完成：进度数据自相矛盾，必须报错。"""
        tasks = [
            make_task("T1", status="todo"),
            make_task("T2", depends_on=["T1"], status="done",
                      actual_minutes=120, completed_at="2026-10-25T18:00:00+08:00"),
        ]
        report = validate(make_state(tasks=tasks))
        self.assertIn("E_PROGRESS", codes(report, "error"))
        message = " ".join(f["message"] for f in report["findings"] if f["code"] == "E_PROGRESS")
        self.assertIn("T1", message)

    # 场景 6 ---------------------------------------------------------------
    def test_06_non_critical_delay_keeps_others_frozen(self):
        """非关键任务延期：只动它自己，不得波及无关任务。"""
        tasks = [
            make_task("T1"),
            make_task("T2", depends_on=["T1"]),
            make_task("T3"),                      # 独立任务
            make_task("T4", depends_on=["T2"]),
        ]
        replan = make_replan(affected=["T2"], moved=["T2"], strategy="S1")
        state = make_state(tasks=tasks, replans=[replan])
        report = validate(state)

        self.assertNotIn("W_ROLLOVER", codes(report, "warning"),
                         "只移动受影响任务时不应报机械顺延")
        closure = Validator(state).downstream_closure(["T2"])
        self.assertEqual(closure, {"T2", "T4"}, "T2 的下游只有 T4，T3 不应被牵连")
        self.assertNotIn("T3", closure)

    # 场景 7 ---------------------------------------------------------------
    def test_07_critical_delay_propagates_downstream(self):
        """关键任务延期影响多个后续任务：允许移动整条链，但不得超出下游闭包。"""
        tasks = [
            make_task("T1"), make_task("T2", depends_on=["T1"]),
            make_task("T3", depends_on=["T2"]), make_task("T4", depends_on=["T3"]),
            make_task("T5"),                      # 另一条链，不该动
        ]
        replan = make_replan(affected=["T1"], moved=["T1", "T2", "T3", "T4"], strategy="S1")
        state = make_state(tasks=tasks, replans=[replan])
        report = validate(state)

        closure = Validator(state).downstream_closure(["T1"])
        self.assertEqual(closure, {"T1", "T2", "T3", "T4"})
        self.assertNotIn("T5", closure)
        self.assertNotIn("W_ROLLOVER", codes(report, "warning"))

        # 越界移动必须被抓出来
        bad = make_replan(rid="R2", affected=["T1"], moved=["T1", "T2", "T5"], strategy="S1")
        bad_report = validate(make_state(tasks=tasks, replans=[bad]))
        self.assertIn("W_ROLLOVER", codes(bad_report, "warning"))
        message = " ".join(f["message"] for f in bad_report["findings"]
                           if f["code"] == "W_ROLLOVER")
        self.assertIn("T5", message)

    # 场景 8 ---------------------------------------------------------------
    def test_08_new_work_squeezes_week(self):
        """新增突发工作：必须重算当周容量，占用超有效容量要提示。"""
        tasks = [
            make_task("T1", scheduled={"week_start": "2026-10-19", "minutes": 700},
                      estimate={"optimistic": 600, "likely": 700, "pessimistic": 800}),
            make_task("T2", scheduled={"week_start": "2026-10-19", "minutes": 200},
                      estimate={"optimistic": 150, "likely": 200, "pessimistic": 300}),
        ]
        replan = make_replan(trigger_type="new_work", affected=["T2"], moved=["T2"],
                             strategy="S1")
        report = validate(make_state(tasks=tasks, replans=[replan]))

        self.assertIn("W_TIGHT_WEEK", codes(report, "warning"),
                      "900 分钟已超有效容量 765，应提示该周没有缓冲")
        self.assertNotIn("E_CAPACITY", codes(report, "error"),
                         "未超硬上限时不应误报为不可行")

    # 场景 9 ---------------------------------------------------------------
    def test_09_hard_deadline_collides_with_workload(self):
        """硬性截止与剩余工作量明显冲突：必须如实报不可行，不许悄悄改截止。"""
        goal = make_goal(deadline="2026-10-30", deadline_rigidity="hard", weight=5)
        tasks = [
            make_task(f"T{i}", scheduled={"week_start": week_start(i),
                                          "minutes": 700},
                      estimate={"optimistic": 600, "likely": 700, "pessimistic": 800})
            for i in range(5)
        ]
        report = validate(make_state(goals=[goal], tasks=tasks))
        self.assertFalse(report["ok"])
        self.assertIn("E_DEADLINE_INFEASIBLE", codes(report, "error"))
        message = " ".join(f["message"] for f in report["findings"]
                           if f["code"] == "E_DEADLINE_INFEASIBLE")
        self.assertIn("2026-10-30", message)
        self.assertIn("缺口", message)
        self.assertEqual(report["verdict"], "infeasible")

    # 场景 10 --------------------------------------------------------------
    def test_10_early_completion_frees_capacity(self):
        """提前完成重要目标：目标与任务都关闭后，不应再占用容量。"""
        goal = make_goal(status="done", deadline="2026-12-01")
        tasks = [
            make_task("T1", status="done", actual_minutes=80,
                      completed_at="2026-10-21T17:00:00+08:00"),
            make_task("T2", depends_on=["T1"], status="done", actual_minutes=100,
                      completed_at="2026-10-22T17:00:00+08:00"),
        ]
        report = validate(make_state(goals=[goal], tasks=tasks))
        self.assertTrue(report["ok"])
        self.assertEqual(report["metrics"]["tasks_open"], 0)
        self.assertEqual(report["metrics"]["effort_likely"], 0, "已完成任务不再计入需求")
        self.assertEqual(report["verdict"], "feasible")

    # 场景 11 --------------------------------------------------------------
    def test_11_priority_change_recorded(self):
        """更改长期目标优先级：记录类型必须是 priority_change，且不得伪造受影响范围。"""
        goals = [
            make_goal("G1", weight=5, deadline="2026-12-01"),
            make_goal("G2", weight=2, deadline="2026-12-15"),
        ]
        tasks = [make_task("T1", "G1"), make_task("T2", "G2")]
        replan = make_replan(trigger_type="priority_change", affected=["T2"], moved=["T2"],
                             strategy="S1", description="G2 优先级由 4 降为 2")
        report = validate(make_state(goals=goals, tasks=tasks, replans=[replan]))
        self.assertTrue(report["ok"])
        self.assertFalse(has_code(report, "W_ROLLOVER"))
        # 权重必须来自用户，不能是模型自填的非法值
        self.assertEqual(goals[0]["weight"], 5)

    # 场景 12 --------------------------------------------------------------
    def test_12_inconsistent_legacy_state_reports_clearly(self):
        """旧计划状态缺失或不一致：必须逐项报错，而不是静默通过。"""
        tasks = [
            make_task("T1", depends_on=["T9"]),                      # 引用不存在
            make_task("T2", goal="G9"),                              # 目标不存在
            make_task("T3", depends_on=["T4"]),
            make_task("T4", depends_on=["T3"]),                      # 依赖成环
            make_task("T5", estimate={"optimistic": 200, "likely": 100, "pessimistic": 50}),
            make_task("T6", scheduled=None),                          # 结构缺失
        ]
        report = validate(make_state(tasks=tasks))
        self.assertFalse(report["ok"])
        found = set(codes(report, "error"))
        for expected in ("E_REF", "E_CYCLE", "E_ESTIMATE_ORDER", "E_SCHEMA"):
            self.assertIn(expected, found, f"缺少 {expected}：实际 {sorted(found)}")
        # 环要指出具体路径，而不是只说"有环"
        cycle_message = " ".join(f["message"] for f in report["findings"]
                                 if f["code"] == "E_CYCLE")
        self.assertIn("T3", cycle_message)
        self.assertIn("T4", cycle_message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
