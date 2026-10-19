#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PlanWeaver 计划校验器（仅依赖 Python 标准库）。

用法:
    python validate_plan.py --state plan-state.json
    python validate_plan.py --state plan-state.json --format text
    python validate_plan.py --state plan-state.json --strict --out report.json

退出码:
    0  无 error
    1  存在 error
    2  输入不可读（文件缺失 / JSON 非法）

设计边界:
    本脚本只判断「数据是否自洽、资源是否够」。它不评价计划的好坏，
    也无法判断动机、健康、家庭责任等非结构化因素。所有涉及时间转换的
    指标均为估算，并在 metrics.assumptions 中声明所用假设。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict

SCHEMA_VERSION = "1.0"
TOOL_VERSION = "1.0.0"

DOMAINS = {"learning", "work", "life", "health", "finance", "longterm", "other"}
RIGIDITY = {"hard", "soft", "open"}
GOAL_STATUS = {"active", "paused", "done", "abandoned"}
TASK_STATUS = {"todo", "doing", "done", "blocked", "dropped"}
VARIANTS = {"baseline", "standard", "sprint"}
TRIGGER_TYPES = {
    "delay", "new_work", "deadline_change", "resource_change",
    "scope_change", "priority_change", "abandon", "early_completion",
}
STRATEGIES = {"S0", "S1", "S2", "S3", "S4", "S5"}
PROGRESS_EVENTS = {"started", "done", "partial", "blocked", "skipped", "estimate_correction"}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d:[0-5]\d(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------

def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_date(value):
    """返回 (date_or_None, ok)。严格 YYYY-MM-DD。"""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None, False
    import datetime
    try:
        return datetime.date.fromisoformat(value), True
    except ValueError:
        return None, False


def parse_time_minutes(value):
    if not isinstance(value, str) or not TIME_RE.match(value):
        return None
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def days_between(a, b):
    return (b - a).days


class Report:
    def __init__(self):
        self.findings = []

    def add(self, level, code, path, message, hint=""):
        self.findings.append({
            "level": level,
            "code": code,
            "path": path,
            "message": message,
            "hint": hint,
        })

    def error(self, code, path, message, hint=""):
        self.add("error", code, path, message, hint)

    def warn(self, code, path, message, hint=""):
        self.add("warning", code, path, message, hint)

    def errors(self):
        return [f for f in self.findings if f["level"] == "error"]

    def warnings(self):
        return [f for f in self.findings if f["level"] == "warning"]


# --------------------------------------------------------------------------
# 校验器
# --------------------------------------------------------------------------

class Validator:
    def __init__(self, state):
        self.state = state
        self.report = Report()
        self.goals = {}
        self.tasks = {}
        self.goal_order = []
        self.task_order = []
        self.horizon_start = None
        self.horizon_end = None
        self.weekly_minutes = None
        self.buffer_ratio = None
        self.daily_capacity = None
        self.fixed_events = []
        self.protected_blocks = []

    # -- 顶层 ---------------------------------------------------------------
    def run(self):
        if not isinstance(self.state, dict):
            self.report.error("E_SCHEMA", "$", "状态文件顶层必须是 JSON 对象",
                              "plan-state.json 的根节点应为 {} 而不是数组或标量")
            return self.finish()

        for key in ("schema_version", "meta", "constraints", "goals", "tasks"):
            if key not in self.state:
                self.report.error("E_SCHEMA", f"$.{key}", f"缺少必填字段 {key}",
                                  "参考 references/state-schema.md 补齐")

        version = self.state.get("schema_version")
        if version is not None and version != SCHEMA_VERSION:
            self.report.error("E_SCHEMA", "$.schema_version",
                              f"不支持的 schema_version：{version!r}（本工具支持 {SCHEMA_VERSION}）",
                              "主版本不同不做静默兼容，请迁移或使用对应版本工具")

        self.check_meta()
        self.check_constraints()
        self.check_goals()
        self.check_tasks()
        self.check_dependencies()
        self.check_progress()
        self.check_schedule()
        self.check_deadlines()
        self.check_replans()
        return self.finish()

    # -- meta ---------------------------------------------------------------
    def check_meta(self):
        meta = self.state.get("meta")
        if not isinstance(meta, dict):
            self.report.error("E_SCHEMA", "$.meta", "meta 必须是对象")
            return

        for key in ("created_at", "updated_at", "revision", "horizon_start", "horizon_end", "active_variant"):
            if key not in meta:
                self.report.error("E_SCHEMA", f"$.meta.{key}", f"meta 缺少 {key}")

        for key in ("created_at", "updated_at"):
            value = meta.get(key)
            if value is not None and not (isinstance(value, str) and DATETIME_RE.match(value)):
                self.report.error("E_DATE", f"$.meta.{key}",
                                  f"{key} 必须是带时区的 ISO 8601 时间戳，当前为 {value!r}",
                                  "示例：2026-10-20T09:00:00+08:00")

        revision = meta.get("revision")
        if revision is not None and (not is_int(revision) or revision < 1):
            self.report.error("E_TYPE", "$.meta.revision", "revision 必须是 ≥ 1 的整数")

        start, ok_s = parse_date(meta.get("horizon_start"))
        end, ok_e = parse_date(meta.get("horizon_end"))
        if not ok_s:
            self.report.error("E_DATE", "$.meta.horizon_start", "horizon_start 必须是 YYYY-MM-DD")
        if not ok_e:
            self.report.error("E_DATE", "$.meta.horizon_end", "horizon_end 必须是 YYYY-MM-DD")
        if ok_s and ok_e:
            if end <= start:
                self.report.error("E_DATE", "$.meta.horizon_end",
                                  "horizon_end 必须晚于 horizon_start",
                                  f"当前 {start} → {end}")
            else:
                self.horizon_start, self.horizon_end = start, end

        variant = meta.get("active_variant")
        if variant is not None and variant not in VARIANTS:
            self.report.error("E_ENUM", "$.meta.active_variant",
                              f"active_variant 必须是 {sorted(VARIANTS)} 之一，当前为 {variant!r}")
        variants = self.state.get("variants")
        if isinstance(variants, dict) and variant is not None and variant not in variants:
            self.report.warn("W_VARIANT_MISSING", "$.meta.active_variant",
                             f"active_variant={variant!r} 在 variants 中没有对应定义",
                             "补上该方案定义，或改成已有方案")

    # -- constraints --------------------------------------------------------
    def check_constraints(self):
        constraints = self.state.get("constraints")
        if not isinstance(constraints, dict):
            self.report.error("E_SCHEMA", "$.constraints", "constraints 必须是对象")
            return

        capacity = constraints.get("capacity")
        if not isinstance(capacity, dict):
            self.report.error("E_SCHEMA", "$.constraints.capacity", "constraints.capacity 必须是对象")
        else:
            weekly = capacity.get("weekly_minutes")
            if not is_int(weekly) or weekly <= 0:
                self.report.error("E_TYPE", "$.constraints.capacity.weekly_minutes",
                                  "weekly_minutes 必须是正整数（真正可投入任务的分钟数）",
                                  "不要填总清醒时间；若只知小时数，乘以 60")
            else:
                self.weekly_minutes = weekly

            ratio = capacity.get("buffer_ratio")
            if not is_num(ratio):
                self.report.error("E_TYPE", "$.constraints.capacity.buffer_ratio",
                                  "buffer_ratio 必须是数字（建议 0.15）")
            elif not (0 <= ratio <= 0.5):
                self.report.error("E_ENUM", "$.constraints.capacity.buffer_ratio",
                                  f"buffer_ratio 必须在 0–0.5 之间，当前 {ratio}",
                                  "超过 0.5 意味着计划只用了不到一半的可用时间")
            else:
                self.buffer_ratio = float(ratio)
                if ratio < 0.05:
                    self.report.warn("W_NO_BUFFER", "$.constraints.capacity.buffer_ratio",
                                     f"缓冲比例仅 {ratio:.0%}，第一次意外就会击穿计划",
                                     "建议 0.15；若历史偏差大，用 0.20–0.25")

            daily = capacity.get("daily_capacity_minutes")
            if daily is not None and (not is_int(daily) or daily <= 0):
                self.report.error("E_TYPE", "$.constraints.capacity.daily_capacity_minutes",
                                  "daily_capacity_minutes 必须是正整数")

        if self.weekly_minutes and self.buffer_ratio is not None:
            daily = self.state.get("constraints", {}).get("capacity", {}).get("daily_capacity_minutes")
            self.daily_capacity = daily if is_int(daily) else self.weekly_minutes / 7.0

        fixed = constraints.get("fixed_events", [])
        if fixed is None:
            fixed = []
        if not isinstance(fixed, list):
            self.report.error("E_TYPE", "$.constraints.fixed_events", "fixed_events 必须是数组")
            fixed = []
        seen = set()
        for idx, event in enumerate(fixed):
            path = f"$.constraints.fixed_events[{idx}]"
            if not isinstance(event, dict):
                self.report.error("E_TYPE", path, "固定日程必须是对象")
                continue
            eid = event.get("id")
            if not isinstance(eid, str) or not eid:
                self.report.error("E_SCHEMA", f"{path}.id", "固定日程缺少 id")
            elif eid in seen:
                self.report.error("E_DUP_ID", f"{path}.id", f"固定日程 id 重复：{eid}")
            else:
                seen.add(eid)
            if not isinstance(event.get("title"), str) or not event.get("title"):
                self.report.error("E_SCHEMA", f"{path}.title", "固定日程缺少 title")

            recurring = event.get("recurring")
            if not isinstance(recurring, bool):
                self.report.error("E_SCHEMA", f"{path}.recurring", "recurring 必须是布尔值")
                recurring = False
            if recurring:
                weekday = event.get("weekday")
                if not is_int(weekday) or not (0 <= weekday <= 6):
                    self.report.error("E_TYPE", f"{path}.weekday",
                                      "循环事件必须给出 weekday（0=周一 … 6=周日）")
            else:
                _, ok = parse_date(event.get("date"))
                if not ok:
                    self.report.error("E_DATE", f"{path}.date", "单次事件必须给出 YYYY-MM-DD 的 date")

            start_m = parse_time_minutes(event.get("start"))
            end_m = parse_time_minutes(event.get("end"))
            if start_m is None:
                self.report.error("E_DATE", f"{path}.start", "start 必须是 HH:MM")
            if end_m is None:
                self.report.error("E_DATE", f"{path}.end", "end 必须是 HH:MM")
            if start_m is not None and end_m is not None and end_m <= start_m:
                self.report.error("E_DATE", f"{path}.end", "end 必须晚于 start")
            if start_m is not None and end_m is not None:
                self.fixed_events.append({
                    "id": eid, "title": event.get("title"), "recurring": recurring,
                    "weekday": event.get("weekday"), "date": event.get("date"),
                    "start": start_m, "end": end_m, "path": path,
                })

        blocks = constraints.get("protected_blocks", [])
        if blocks is None:
            blocks = []
        if not isinstance(blocks, list):
            self.report.error("E_TYPE", "$.constraints.protected_blocks", "protected_blocks 必须是数组")
            blocks = []
        seen = set()
        for idx, block in enumerate(blocks):
            path = f"$.constraints.protected_blocks[{idx}]"
            if not isinstance(block, dict):
                self.report.error("E_TYPE", path, "受保护时段必须是对象")
                continue
            bid = block.get("id")
            if not isinstance(bid, str) or not bid:
                self.report.error("E_SCHEMA", f"{path}.id", "受保护时段缺少 id")
            elif bid in seen:
                self.report.error("E_DUP_ID", f"{path}.id", f"受保护时段 id 重复：{bid}")
            else:
                seen.add(bid)
            if not isinstance(block.get("label"), str) or not block.get("label"):
                self.report.error("E_SCHEMA", f"{path}.label", "受保护时段缺少 label（如 睡眠 / 运动）")

            daily = block.get("daily_minutes")
            has_daily = is_int(daily) and daily >= 0
            has_window = block.get("start") is not None and block.get("end") is not None
            if not has_daily and not has_window:
                self.report.error("E_SCHEMA", path,
                                  "受保护时段需要 daily_minutes，或 start+end 时段",
                                  "例：{\"id\":\"P1\",\"label\":\"睡眠\",\"daily_minutes\":480}")
            if daily is not None and not has_daily:
                self.report.error("E_TYPE", f"{path}.daily_minutes", "daily_minutes 必须是 ≥ 0 的整数")

            entry = {"id": bid, "label": block.get("label"), "daily_minutes": daily if has_daily else None,
                     "rigid": block.get("rigid", True), "path": path,
                     "start": None, "end": None}
            if has_window:
                s = parse_time_minutes(block.get("start"))
                e = parse_time_minutes(block.get("end"))
                if s is None or e is None:
                    self.report.error("E_DATE", path, "受保护时段的 start/end 必须是 HH:MM")
                elif e <= s:
                    self.report.error("E_DATE", f"{path}.end", "end 必须晚于 start")
                else:
                    entry["start"], entry["end"] = s, e
            self.protected_blocks.append(entry)

    # -- goals --------------------------------------------------------------
    def check_goals(self):
        goals = self.state.get("goals")
        if not isinstance(goals, list):
            self.report.error("E_SCHEMA", "$.goals", "goals 必须是数组")
            return
        if not goals:
            self.report.error("E_SCHEMA", "$.goals", "至少需要一个目标",
                              "没有目标就没有可规划的对象")

        for idx, goal in enumerate(goals):
            path = f"$.goals[{idx}]"
            if not isinstance(goal, dict):
                self.report.error("E_TYPE", path, "目标必须是对象")
                continue
            gid = goal.get("id")
            if not isinstance(gid, str) or not gid:
                self.report.error("E_SCHEMA", f"{path}.id", "目标缺少 id")
                continue
            if gid in self.goals:
                self.report.error("E_DUP_ID", f"{path}.id", f"目标 id 重复：{gid}")
                continue
            self.goals[gid] = goal
            self.goal_order.append(gid)

            if not isinstance(goal.get("name"), str) or not goal.get("name"):
                self.report.error("E_SCHEMA", f"{path}.name", "目标缺少 name")

            domain = goal.get("domain")
            if domain not in DOMAINS:
                self.report.error("E_ENUM", f"{path}.domain",
                                  f"domain 必须是 {sorted(DOMAINS)} 之一，当前为 {domain!r}")

            rigidity = goal.get("deadline_rigidity")
            if rigidity not in RIGIDITY:
                self.report.error("E_ENUM", f"{path}.deadline_rigidity",
                                  f"deadline_rigidity 必须是 {sorted(RIGIDITY)} 之一，当前为 {rigidity!r}")

            deadline_raw = goal.get("deadline", "MISSING")
            if deadline_raw == "MISSING":
                self.report.error("E_SCHEMA", f"{path}.deadline",
                                  "缺少 deadline 字段", "无期限时显式写 null，并设 deadline_rigidity=open")
            elif deadline_raw is not None:
                d, ok = parse_date(deadline_raw)
                if not ok:
                    self.report.error("E_DATE", f"{path}.deadline", "deadline 必须是 YYYY-MM-DD 或 null")
                elif rigidity == "hard" and self.horizon_end and d > self.horizon_end:
                    self.report.warn("W_DEADLINE_OUTSIDE", f"{path}.deadline",
                                     f"硬截止 {d} 超出计划窗口（止于 {self.horizon_end}）",
                                     "扩展 horizon_end，否则无法校验该截止的可行性")
            else:
                if rigidity == "hard":
                    self.report.error("E_SCHEMA", f"{path}.deadline",
                                      "硬性截止的目标不能没有 deadline")
                else:
                    self.report.warn("W_GOAL_NO_DEADLINE", f"{path}.deadline",
                                     f"目标 {gid} 没有截止日期",
                                     "无期限目标只能给下一步动作，无法给路线图；建议补一个目标日期")

            weight = goal.get("weight")
            if not is_int(weight) or not (1 <= weight <= 5):
                self.report.error("E_TYPE", f"{path}.weight",
                                  "weight 必须是 1–5 的整数（由用户给定，模型不得代填）")

            status = goal.get("status")
            if status not in GOAL_STATUS:
                self.report.error("E_ENUM", f"{path}.status",
                                  f"status 必须是 {sorted(GOAL_STATUS)} 之一，当前为 {status!r}")

            criteria = goal.get("acceptance_criteria")
            if not isinstance(criteria, list):
                self.report.error("E_SCHEMA", f"{path}.acceptance_criteria",
                                  "acceptance_criteria 必须是数组")
            elif not criteria:
                self.report.warn("W_NO_ACCEPTANCE", f"{path}.acceptance_criteria",
                                 f"目标 {gid} 没有可验证的完成标准",
                                 "没有验收标准就无法判断计划是否成功")

    # -- tasks --------------------------------------------------------------
    def check_tasks(self):
        self.tasks.clear()
        self.task_order.clear()
        tasks = self.state.get("tasks")
        if not isinstance(tasks, list):
            self.report.error("E_SCHEMA", "$.tasks", "tasks 必须是数组")
            return
        if not tasks:
            self.report.error("E_SCHEMA", "$.tasks", "至少需要一个任务")

        for idx, task in enumerate(tasks):
            path = f"$.tasks[{idx}]"
            if not isinstance(task, dict):
                self.report.error("E_TYPE", path, "任务必须是对象")
                continue
            tid = task.get("id")
            if not isinstance(tid, str) or not tid:
                self.report.error("E_SCHEMA", f"{path}.id", "任务缺少 id")
                continue
            if tid in self.tasks:
                self.report.error("E_DUP_ID", f"{path}.id", f"任务 id 重复：{tid}")
                continue
            self.tasks[tid] = task
            self.task_order.append(tid)

            if not isinstance(task.get("title"), str) or not task.get("title"):
                self.report.error("E_SCHEMA", f"{path}.title", "任务缺少 title")

            goal_id = task.get("goal_id")
            if not isinstance(goal_id, str) or not goal_id:
                self.report.error("E_SCHEMA", f"{path}.goal_id", "任务缺少 goal_id")
            elif self.goals and goal_id not in self.goals:
                self.report.error("E_REF", f"{path}.goal_id",
                                  f"引用了不存在的目标 {goal_id!r}",
                                  f"可用目标：{', '.join(self.goal_order) or '（无）'}")

            estimate = task.get("estimate")
            if not isinstance(estimate, dict):
                self.report.error("E_SCHEMA", f"{path}.estimate",
                                  "estimate 必须是 {optimistic, likely, pessimistic} 对象")
            else:
                values = {}
                for key in ("optimistic", "likely", "pessimistic"):
                    value = estimate.get(key)
                    if not is_int(value) or value <= 0:
                        self.report.error("E_TYPE", f"{path}.estimate.{key}",
                                          f"{key} 必须是正整数（分钟）")
                    else:
                        values[key] = value
                if len(values) == 3:
                    if not (values["optimistic"] <= values["likely"] <= values["pessimistic"]):
                        self.report.error("E_ESTIMATE_ORDER", f"{path}.estimate",
                                          "三点估算必须满足 optimistic ≤ likely ≤ pessimistic，"
                                          f"当前为 {values['optimistic']}/{values['likely']}/{values['pessimistic']}")
                    if values["likely"] > 240:
                        self.report.warn("W_TASK_TOO_BIG", f"{path}.estimate.likely",
                                         f"任务 {tid} 估算 {values['likely']} 分钟（> 4 小时），建议拆分",
                                         "颗粒度 30 分钟–4 小时最利于执行与重排")

            deps = task.get("depends_on")
            if not isinstance(deps, list):
                self.report.error("E_SCHEMA", f"{path}.depends_on", "depends_on 必须是数组（可为空）")
            else:
                for dep in deps:
                    if not isinstance(dep, str):
                        self.report.error("E_TYPE", f"{path}.depends_on", "depends_on 的元素必须是字符串 id")
                    elif dep == tid:
                        self.report.error("E_CYCLE", f"{path}.depends_on", f"任务 {tid} 依赖了自己")

            scheduled = task.get("scheduled")
            if not isinstance(scheduled, dict):
                self.report.error("E_SCHEMA", f"{path}.scheduled",
                                  "scheduled 必须是对象（至少含 week_start 与 minutes）")
            else:
                _, ok = parse_date(scheduled.get("week_start"))
                if not ok:
                    self.report.error("E_DATE", f"{path}.scheduled.week_start",
                                      "week_start 必须是 YYYY-MM-DD")
                minutes = scheduled.get("minutes")
                if not is_int(minutes) or minutes < 0:
                    self.report.error("E_TYPE", f"{path}.scheduled.minutes",
                                      "scheduled.minutes 必须是 ≥ 0 的整数")

            status = task.get("status")
            if status not in TASK_STATUS:
                self.report.error("E_ENUM", f"{path}.status",
                                  f"status 必须是 {sorted(TASK_STATUS)} 之一，当前为 {status!r}")

            actual = task.get("actual_minutes", 0)
            if not is_int(actual) or actual < 0:
                self.report.error("E_TYPE", f"{path}.actual_minutes",
                                  "actual_minutes 必须是 ≥ 0 的整数")

            due_raw = task.get("due")
            if due_raw is not None:
                _, ok = parse_date(due_raw)
                if not ok:
                    self.report.error("E_DATE", f"{path}.due", "due 必须是 YYYY-MM-DD 或 null")

            compression_safe = task.get("compression_safe", False)
            if not isinstance(compression_safe, bool):
                self.report.error("E_TYPE", f"{path}.compression_safe", "compression_safe 必须是布尔值")

            blocks = task.get("blocks")
            if blocks is not None:
                if not isinstance(blocks, list):
                    self.report.error("E_TYPE", f"{path}.blocks", "blocks 必须是数组")
                else:
                    for bidx, block in enumerate(blocks):
                        bpath = f"{path}.blocks[{bidx}]"
                        if not isinstance(block, dict):
                            self.report.error("E_TYPE", bpath, "时间块必须是对象")
                            continue
                        _, ok = parse_date(block.get("date"))
                        if not ok:
                            self.report.error("E_DATE", f"{bpath}.date", "时间块 date 必须是 YYYY-MM-DD")
                        s = parse_time_minutes(block.get("start"))
                        e = parse_time_minutes(block.get("end"))
                        if s is None:
                            self.report.error("E_DATE", f"{bpath}.start", "start 必须是 HH:MM")
                        if e is None:
                            self.report.error("E_DATE", f"{bpath}.end", "end 必须是 HH:MM")
                        if s is not None and e is not None and e <= s:
                            self.report.error("E_DATE", f"{bpath}.end", "end 必须晚于 start")

    # -- dependencies -------------------------------------------------------
    def check_dependencies(self):
        if not self.tasks:
            return
        for tid in self.task_order:
            deps = self.tasks[tid].get("depends_on") or []
            if not isinstance(deps, list):
                continue
            for dep in deps:
                if isinstance(dep, str) and dep != tid and dep not in self.tasks:
                    self.report.error("E_REF", f"$.tasks[{self.task_order.index(tid)}].depends_on",
                                      f"任务 {tid} 依赖了不存在的任务 {dep!r}",
                                      f"可用任务：{', '.join(self.task_order)}")

        cycle = self.find_cycle()
        if cycle:
            self.report.error("E_CYCLE", "$.tasks",
                              "任务依赖存在环：" + " → ".join(cycle),
                              "环上的任务永远无法开始，必须打破其中一个依赖")

    def find_cycle(self):
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {tid: WHITE for tid in self.task_order}
        stack = []

        def visit(node):
            color[node] = GRAY
            stack.append(node)
            deps = self.tasks[node].get("depends_on") or []
            for dep in deps:
                if not isinstance(dep, str) or dep not in self.tasks:
                    continue
                if color[dep] == GRAY:
                    idx = stack.index(dep)
                    return stack[idx:] + [dep]
                if color[dep] == WHITE:
                    found = visit(dep)
                    if found:
                        return found
            stack.pop()
            color[node] = BLACK
            return None

        for tid in self.task_order:
            if color[tid] == WHITE:
                found = visit(tid)
                if found:
                    return found
        return None

    def _ensure_index(self):
        """在未执行完整校验时也能做图计算（供外部直接调用图算法）。"""
        if self.tasks:
            return
        tasks = self.state.get("tasks") if isinstance(self.state, dict) else None
        if isinstance(tasks, list):
            for task in tasks:
                if isinstance(task, dict) and isinstance(task.get("id"), str):
                    self.tasks[task["id"]] = task
                    self.task_order.append(task["id"])

    def children_map(self):
        """dep -> [依赖它的任务]"""
        self._ensure_index()
        children = defaultdict(list)
        for tid in self.task_order:
            for dep in self.tasks[tid].get("depends_on") or []:
                if isinstance(dep, str):
                    children[dep].append(tid)
        return children

    def downstream_closure(self, seeds):
        self._ensure_index()
        children = self.children_map()
        seen = set()
        queue = [s for s in seeds if s in self.tasks]
        while queue:
            node = queue.pop()
            if node in seen:
                continue
            seen.add(node)
            queue.extend(children.get(node, []))
        return seen

    # -- progress -----------------------------------------------------------
    def check_progress(self):
        for idx, tid in enumerate(self.task_order):
            task = self.tasks[tid]
            path = f"$.tasks[{idx}]"
            status = task.get("status")
            actual = task.get("actual_minutes", 0)
            completed = task.get("completed_at")

            if status == "done":
                if not completed and (not is_int(actual) or actual <= 0):
                    self.report.error("E_PROGRESS", path,
                                      f"任务 {tid} 标记为 done，但没有 completed_at 也没有实际耗时",
                                      "至少记录一项，否则校准无法进行")
                if completed is not None and not (isinstance(completed, str) and DATETIME_RE.match(completed)):
                    self.report.error("E_DATE", f"{path}.completed_at",
                                      "completed_at 必须是 ISO 8601 时间戳或 null")
                for dep in task.get("depends_on") or []:
                    dep_task = self.tasks.get(dep) if isinstance(dep, str) else None
                    if dep_task and dep_task.get("status") not in ("done", "dropped"):
                        self.report.error("E_PROGRESS", path,
                                          f"任务 {tid} 已完成，但其前置任务 {dep} 尚未完成"
                                          f"（当前 {dep_task.get('status')}）",
                                          "要么前置实际已完成（补状态），要么该任务并未真正完成")

            if is_int(actual) and actual > 0 and status == "todo":
                self.report.warn("W_PROGRESS", path,
                                 f"任务 {tid} 有实际耗时 {actual} 分钟但状态是 todo",
                                 "把状态改为 doing 或 done，否则进度统计会失真")

            if status == "doing" and is_int(actual) and actual == 0:
                self.report.warn("W_PROGRESS", path,
                                 f"任务 {tid} 状态为 doing 但实际耗时为 0",
                                 "补记已投入时间，校准才有依据")

            if status == "done":
                scheduled = task.get("scheduled") or {}
                if is_int(scheduled.get("minutes")) and scheduled["minutes"] > 0 \
                        and is_int(actual) and actual > 0 and actual > scheduled["minutes"] * 2.5:
                    self.report.warn("W_ESTIMATE_DRIFT", path,
                                     f"任务 {tid} 实际 {actual} 分钟，是排期 {scheduled['minutes']} 分钟的 "
                                     f"{actual / scheduled['minutes']:.1f} 倍",
                                     "记录到 calibration.bias_by_category，下一版估算按类别上调")

    # -- schedule -----------------------------------------------------------
    def check_schedule(self):
        if not self.weekly_minutes or self.buffer_ratio is None:
            return
        effective_week = self.weekly_minutes * (1 - self.buffer_ratio)
        week_load = defaultdict(int)
        week_tasks = defaultdict(list)

        for idx, tid in enumerate(self.task_order):
            task = self.tasks[tid]
            if task.get("status") in ("done", "dropped"):
                continue
            scheduled = task.get("scheduled")
            if not isinstance(scheduled, dict):
                continue
            week_start, ok = parse_date(scheduled.get("week_start"))
            minutes = scheduled.get("minutes")
            if not ok or not is_int(minutes):
                continue
            key = week_start.isoformat()
            week_load[key] += minutes
            week_tasks[key].append(tid)

            if self.horizon_start and self.horizon_end:
                if week_start < self.horizon_start or week_start > self.horizon_end:
                    self.report.warn("W_SCHEDULE_OUTSIDE", f"$.tasks[{idx}].scheduled.week_start",
                                     f"任务 {tid} 排期 {key} 超出计划窗口 "
                                     f"{self.horizon_start}–{self.horizon_end}",
                                     "扩展窗口或调整排期，否则该任务不会被计入可行性判断")

        for week in sorted(week_load):
            load = week_load[week]
            if load > self.weekly_minutes:
                self.report.error("E_CAPACITY", "$.tasks",
                                  f"{week} 这一周任务量 {load} 分钟，超过周可用时间 {self.weekly_minutes} 分钟",
                                  f"涉及任务：{', '.join(week_tasks[week])}；必须减任务或加时间")
            elif load > effective_week:
                self.report.warn("W_TIGHT_WEEK", "$.tasks",
                                 f"{week} 这一周占用 {load} 分钟，超过有效容量 "
                                 f"{effective_week:.0f} 分钟（含 {self.buffer_ratio:.0%} 缓冲）",
                                 f"涉及任务：{', '.join(week_tasks[week])}；该周没有容错空间")

        self.check_time_blocks()

    def check_time_blocks(self):
        """检测具体时间块与固定日程、受保护时段、单日总时长的冲突。"""
        by_date = defaultdict(list)
        for idx, tid in enumerate(self.task_order):
            task = self.tasks[tid]
            if task.get("status") in ("done", "dropped"):
                continue
            for bidx, block in enumerate(task.get("blocks") or []):
                if not isinstance(block, dict):
                    continue
                date, ok = parse_date(block.get("date"))
                s = parse_time_minutes(block.get("start"))
                e = parse_time_minutes(block.get("end"))
                if not ok or s is None or e is None or e <= s:
                    continue
                by_date[date].append({
                    "task": tid, "start": s, "end": e,
                    "path": f"$.tasks[{idx}].blocks[{bidx}]",
                })

        if not by_date:
            return

        for date in sorted(by_date):
            blocks = sorted(by_date[date], key=lambda b: b["start"])

            # 任务块互相重叠
            for i in range(len(blocks) - 1):
                if blocks[i]["end"] > blocks[i + 1]["start"]:
                    self.report.error("E_OVERLAP", blocks[i + 1]["path"],
                                      f"{date} 任务 {blocks[i]['task']} 与 {blocks[i + 1]['task']} "
                                      f"时间重叠",
                                      "同一时段只能安排一个任务；若确实并行，请合并为一个任务")

            # 与固定日程重叠
            for event in self.fixed_events:
                applies = False
                if event["recurring"]:
                    applies = (date.weekday() == event["weekday"])
                else:
                    applies = (event["date"] == date.isoformat())
                if not applies:
                    continue
                for block in blocks:
                    if block["start"] < event["end"] and event["start"] < block["end"]:
                        self.report.error("E_OVERLAP", block["path"],
                                          f"{date} 任务 {block['task']}（{self._hhmm(block['start'])}–"
                                          f"{self._hhmm(block['end'])}）与固定日程 "
                                          f"{event['title']}（{self._hhmm(event['start'])}–"
                                          f"{self._hhmm(event['end'])}）冲突",
                                          "固定安排不可移动，请把任务挪到其他时段")

            # 与刚性受保护时段重叠
            for block_prot in self.protected_blocks:
                if block_prot["start"] is None or not block_prot.get("rigid", True):
                    continue
                for block in blocks:
                    if block["start"] < block_prot["end"] and block_prot["start"] < block["end"]:
                        self.report.error("E_PROTECTED", block["path"],
                                          f"{date} 任务 {block['task']} 侵占了受保护时段 "
                                          f"{block_prot['label']}（{self._hhmm(block_prot['start'])}–"
                                          f"{self._hhmm(block_prot['end'])}）",
                                          "睡眠/恢复时间不可用任务填补；这是硬约束")

            # 单日总时长超限
            used = sum(b["end"] - b["start"] for b in blocks)
            fixed_minutes = 0
            for event in self.fixed_events:
                if event["recurring"] and date.weekday() == event["weekday"]:
                    fixed_minutes += event["end"] - event["start"]
                elif not event["recurring"] and event["date"] == date.isoformat():
                    fixed_minutes += event["end"] - event["start"]
            protected_daily = sum(p["daily_minutes"] or 0 for p in self.protected_blocks)
            if used + fixed_minutes + protected_daily > 1440:
                self.report.error("E_PROTECTED", blocks[0]["path"],
                                  f"{date} 安排总量超出一天：任务 {used} + 固定 {fixed_minutes} + "
                                  f"受保护 {protected_daily} = {used + fixed_minutes + protected_daily} 分钟 > 1440",
                                  "这一天排不下，需要减少任务或换日")

    @staticmethod
    def _hhmm(minutes):
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    # -- deadlines ----------------------------------------------------------
    def check_deadlines(self):
        if not (self.horizon_start and self.weekly_minutes and self.buffer_ratio is not None):
            return

        # 依赖顺序：前置的截止不能晚于后继
        for idx, tid in enumerate(self.task_order):
            task = self.tasks[tid]
            due, ok = parse_date(task.get("due"))
            if not ok:
                continue
            for dep in task.get("depends_on") or []:
                dep_task = self.tasks.get(dep) if isinstance(dep, str) else None
                if not dep_task:
                    continue
                dep_due, dep_ok = parse_date(dep_task.get("due"))
                if dep_ok and dep_due > due:
                    self.report.error("E_DEP_DEADLINE", f"$.tasks[{idx}].due",
                                      f"任务 {tid} 截止 {due}，但其前置 {dep} 截止 {dep_due}，"
                                      f"前置晚于后继，顺序不可能成立",
                                      "调整两者截止日期，使前置早于后继")

        # 硬截止累计负荷
        hard_goals = []
        for gid in self.goal_order:
            goal = self.goals[gid]
            if goal.get("deadline_rigidity") != "hard":
                continue
            if goal.get("status") != "active":
                continue
            deadline, ok = parse_date(goal.get("deadline"))
            if not ok:
                continue
            hard_goals.append((deadline, gid))
        hard_goals.sort()

        effective_daily = self.weekly_minutes * (1 - self.buffer_ratio) / 7.0
        checked = set()
        for deadline, gid in hard_goals:
            if deadline in checked:
                continue
            checked.add(deadline)
            days = days_between(self.horizon_start, deadline)
            if days <= 0:
                self.report.error("E_DEADLINE_INFEASIBLE", f"$.goals[{self.goal_order.index(gid)}].deadline",
                                  f"目标 {gid} 的硬截止 {deadline} 不在计划窗口内（起点 {self.horizon_start}）")
                continue
            capacity = effective_daily * days
            demand = 0
            involved = []
            for tid in self.task_order:
                task = self.tasks[tid]
                if task.get("status") in ("done", "dropped"):
                    continue
                goal = self.goals.get(task.get("goal_id"), {})
                goal_deadline, goal_ok = parse_date(goal.get("deadline"))
                week_start, week_ok = parse_date((task.get("scheduled") or {}).get("week_start"))
                belongs = goal_ok and goal_deadline <= deadline
                scheduled_before = week_ok and week_start <= deadline
                if belongs or scheduled_before:
                    estimate = task.get("estimate") or {}
                    likely = estimate.get("likely")
                    if is_int(likely):
                        demand += likely
                        involved.append(tid)
            if demand > capacity:
                self.report.error("E_DEADLINE_INFEASIBLE", "$.tasks",
                                  f"到 {deadline}（目标 {gid} 的硬截止）为止，需完成 {demand} 分钟，"
                                  f"但按有效容量只能完成 {capacity:.0f} 分钟，缺口 {demand - capacity:.0f} 分钟",
                                  f"涉及任务：{', '.join(involved)}；硬截止不可延，"
                                  f"只能缩小范围、加资源或放弃部分目标")

    # -- replans ------------------------------------------------------------
    def check_replans(self):
        replans = self.state.get("replans")
        if replans is None:
            return
        if not isinstance(replans, list):
            self.report.error("E_TYPE", "$.replans", "replans 必须是数组")
            return

        open_tasks = [tid for tid in self.task_order
                      if self.tasks[tid].get("status") not in ("done", "dropped")]

        for idx, replan in enumerate(replans):
            path = f"$.replans[{idx}]"
            if not isinstance(replan, dict):
                self.report.error("E_TYPE", path, "重规划记录必须是对象")
                continue

            trigger = replan.get("trigger")
            if not isinstance(trigger, dict):
                self.report.error("E_SCHEMA", f"{path}.trigger", "缺少 trigger 对象")
                continue

            ttype = trigger.get("type")
            if ttype not in TRIGGER_TYPES:
                self.report.error("E_ENUM", f"{path}.trigger.type",
                                  f"trigger.type 必须是 {sorted(TRIGGER_TYPES)} 之一，当前为 {ttype!r}")

            if not isinstance(trigger.get("description"), str) or not trigger.get("description"):
                self.report.error("E_SCHEMA", f"{path}.trigger.description",
                                  "缺少变化事实描述")

            affected = trigger.get("affected_task_ids")
            if not isinstance(affected, list):
                self.report.error("E_SCHEMA", f"{path}.trigger.affected_task_ids",
                                  "affected_task_ids 必须是数组（直接受影响的任务）")
                affected = []
            for tid in affected:
                if not isinstance(tid, str) or tid not in self.tasks:
                    self.report.error("E_REF", f"{path}.trigger.affected_task_ids",
                                      f"引用了不存在的任务 {tid!r}")

            moved = replan.get("moved_task_ids")
            if not isinstance(moved, list):
                self.report.error("E_SCHEMA", f"{path}.moved_task_ids",
                                  "moved_task_ids 必须是数组（实际被改动的任务）")
                moved = []
            for tid in moved:
                if not isinstance(tid, str) or tid not in self.tasks:
                    self.report.error("E_REF", f"{path}.moved_task_ids",
                                      f"引用了不存在的任务 {tid!r}")

            strategy = replan.get("strategy")
            if strategy not in STRATEGIES:
                self.report.error("E_ENUM", f"{path}.strategy",
                                  f"strategy 必须是 S0–S5 之一，当前为 {strategy!r}")

            if not isinstance(replan.get("approved_by_user"), bool):
                self.report.error("E_SCHEMA", f"{path}.approved_by_user",
                                  "approved_by_user 必须是布尔值")

            valid_affected = [t for t in affected if isinstance(t, str) and t in self.tasks]
            closure = self.downstream_closure(valid_affected) if valid_affected else set()
            valid_moved = [t for t in moved if isinstance(t, str) and t in self.tasks]

            # 机械顺延检测：移动了不受影响的任务
            outside = [t for t in valid_moved if t not in closure]
            if valid_affected and outside:
                self.report.warn("W_ROLLOVER", f"{path}.moved_task_ids",
                                 f"本次重规划移动了 {len(outside)} 个与变化无依赖关系的任务："
                                 f"{', '.join(outside)}",
                                 "这些任务不受影响，应保持原排期；把它们一起后移会造成假延期")
            if not valid_affected and valid_moved:
                self.report.warn("W_ROLLOVER", f"{path}.trigger.affected_task_ids",
                                 "没有声明任何受影响任务，却移动了任务",
                                 "先算影响域，再改排期")

            # 大比例移动
            if len(valid_moved) > 2 and open_tasks:
                ratio = len(valid_moved) / len(open_tasks)
                if ratio > 0.7:
                    self.report.warn("W_ROLLOVER_MASS", f"{path}.moved_task_ids",
                                     f"本次重规划移动了 {len(valid_moved)}/{len(open_tasks)} "
                                     f"（{ratio:.0%}）未完成任务，疑似全量顺延",
                                     "检查是否真的所有任务都受影响；通常只有一条链需要改")

            # 策略与动作一致性
            if strategy == "S0" and valid_moved:
                self.report.warn("W_STRATEGY_MISMATCH", f"{path}.strategy",
                                 f"S0（吸收）表示不改排期，但记录里移动了 {len(valid_moved)} 个任务",
                                 "S0 只更新进度；若要改排期，应使用 S1 及以上")
            if strategy == "S2":
                unsafe = [t for t in valid_moved if not self.tasks[t].get("compression_safe", False)]
                if unsafe:
                    self.report.warn("W_COMPRESSION_UNSAFE", f"{path}.moved_task_ids",
                                     f"S2 压缩涉及未标记 compression_safe 的任务：{', '.join(unsafe)}",
                                     "仅机械性、可批处理的任务允许压缩；其余应改走 S1 或 S3")
            if strategy == "S4":
                for tid in valid_moved or valid_affected:
                    goal = self.goals.get(self.tasks[tid].get("goal_id"), {})
                    if goal.get("deadline_rigidity") == "hard":
                        self.report.error("E_STRATEGY_HARD_DEADLINE_EXTEND", f"{path}.strategy",
                                          f"S4（延长期限）用在了硬性截止目标 {goal.get('id')} 上",
                                          "硬性截止不可延；应改用 S3 降级或 S5 让用户决策")
                        break

    # -- 汇总 ---------------------------------------------------------------
    def finish(self):
        metrics = self.compute_metrics()
        for tid in metrics.get("negative_slack_tasks", []):
            self.report.warn("W_NEGATIVE_SLACK", f"$.tasks[{self.task_order.index(tid)}].due",
                             f"任务 {tid} 按当前排期的最早完成时间比截止日晚 "
                             f"{abs(metrics['slack_days'][tid]):.1f} 天",
                             "把排期提前、拆分任务或调整截止；硬截止不可延")
        errors = self.report.errors()
        warnings = self.report.warnings()

        verdict = metrics.get("verdict", "unknown")
        if any(f["code"] in ("E_CAPACITY", "E_DEADLINE_INFEASIBLE") for f in errors):
            verdict = "infeasible"

        return {
            "ok": len(errors) == 0,
            "tool": f"planweaver-validate/{TOOL_VERSION}",
            "schema_version": SCHEMA_VERSION,
            "verdict": verdict,
            "counts": {"errors": len(errors), "warnings": len(warnings)},
            "findings": self.report.findings,
            "metrics": metrics,
        }

    def compute_metrics(self):
        metrics = {
            "assumptions": [
                "日容量 = weekly_minutes / 7（未指定 daily_capacity_minutes 时）",
                "有效容量已扣除 buffer_ratio",
                "关键路径按 likely 估算求和，未计入并行任务争抢同一时段的影响",
                "余量按自然日折算，最早开始取依赖链完成与排期周起点的较大者，不含固定日程的日历效应",
            ],
            "tasks_total": len(self.task_order),
            "tasks_open": 0,
            "effort_optimistic": 0,
            "effort_likely": 0,
            "effort_pessimistic": 0,
            "effective_capacity": None,
            "utilization": None,
            "verdict": "unknown",
            "critical_path": [],
            "critical_path_minutes": 0,
            "critical_path_days": None,
            "min_slack_days": None,
            "negative_slack_tasks": [],
        }
        if not self.task_order:
            return metrics

        open_tasks = [t for t in self.task_order if self.tasks[t].get("status") not in ("done", "dropped")]
        metrics["tasks_open"] = len(open_tasks)

        for tid in open_tasks:
            estimate = self.tasks[tid].get("estimate") or {}
            for key, target in (("optimistic", "effort_optimistic"),
                                ("likely", "effort_likely"),
                                ("pessimistic", "effort_pessimistic")):
                value = estimate.get(key)
                if is_int(value):
                    metrics[target] += value

        if self.horizon_start and self.horizon_end and self.weekly_minutes and self.buffer_ratio is not None:
            days = max(1, days_between(self.horizon_start, self.horizon_end))
            effective = self.weekly_minutes * (1 - self.buffer_ratio) * days / 7.0
            metrics["effective_capacity"] = round(effective, 1)
            if effective > 0:
                metrics["utilization"] = round(metrics["effort_likely"] / effective, 3)

            if metrics["effort_pessimistic"] <= effective:
                verdict = "feasible"
            elif metrics["effort_likely"] <= effective:
                verdict = "tight"
            else:
                verdict = "infeasible"
            metrics["verdict"] = verdict

        # 关键路径（按 likely 求和，拓扑序）
        dist = {}
        prev = {}
        for tid in self._topo_order():
            deps = [d for d in (self.tasks[tid].get("depends_on") or [])
                    if isinstance(d, str) and d in self.tasks]
            best, best_dep = 0, None
            for dep in deps:
                if dist.get(dep, 0) > best:
                    best, best_dep = dist[dep], dep
            own = (self.tasks[tid].get("estimate") or {}).get("likely")
            own = own if is_int(own) else 0
            dist[tid] = best + own
            prev[tid] = best_dep

        if dist:
            end = max(dist, key=lambda k: dist[k])
            path = []
            node = end
            while node is not None:
                path.append(node)
                node = prev.get(node)
            path.reverse()
            metrics["critical_path"] = path
            metrics["critical_path_minutes"] = dist[end]
            if self.daily_capacity:
                metrics["critical_path_days"] = round(dist[end] / self.daily_capacity, 1)

        # 余量（天）：最早开始取「依赖链完成」与「排期周起点」的较大者，
        # 否则会高估余量——任务不可能早于它被安排的那一周开始。
        if self.horizon_start and self.daily_capacity:
            es = {}
            for tid in self._topo_order():
                deps = [d for d in (self.tasks[tid].get("depends_on") or [])
                        if isinstance(d, str) and d in self.tasks]
                start = 0
                for dep in deps:
                    start = max(start, es.get(dep, 0))
                week_start, week_ok = parse_date((self.tasks[tid].get("scheduled") or {})
                                                 .get("week_start"))
                if week_ok:
                    offset = days_between(self.horizon_start, week_start) * self.daily_capacity
                    if offset > start:
                        start = offset
                own = (self.tasks[tid].get("estimate") or {}).get("likely")
                own = own if is_int(own) else 0
                due, ok = parse_date(self.tasks[tid].get("due"))
                if ok and self.tasks[tid].get("status") not in ("done", "dropped"):
                    finish_days = (start + own) / self.daily_capacity
                    slack = days_between(self.horizon_start, due) - finish_days
                    metrics.setdefault("slack_days", {})[tid] = round(slack, 1)
                    if metrics["min_slack_days"] is None or slack < metrics["min_slack_days"]:
                        metrics["min_slack_days"] = round(slack, 1)
                    if slack < 0:
                        metrics["negative_slack_tasks"].append(tid)
                es[tid] = start + own

        return metrics

    def _topo_order(self):
        order = []
        visited = set()

        def visit(node):
            if node in visited:
                return
            visited.add(node)
            for dep in self.tasks[node].get("depends_on") or []:
                if isinstance(dep, str) and dep in self.tasks:
                    visit(dep)
            order.append(node)

        for tid in self.task_order:
            visit(tid)
        return order


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------

def render_text(report):
    lines = []
    counts = report["counts"]
    verdict = report["verdict"]
    verdict_zh = {"feasible": "可行", "tight": "紧张", "infeasible": "不可行"}.get(verdict, verdict)
    lines.append(f"PlanWeaver 校验结果：{'通过' if report['ok'] else '未通过'}")
    lines.append(f"可行性判定：{verdict_zh}")
    metrics = report["metrics"]
    if metrics.get("effective_capacity"):
        lines.append(f"有效容量：{metrics['effective_capacity']:.0f} 分钟 | "
                     f"需求（通常）：{metrics['effort_likely']} 分钟 | "
                     f"需求（保守）：{metrics['effort_pessimistic']} 分钟")
        if metrics.get("utilization") is not None:
            lines.append(f"占用率：{metrics['utilization']:.0%}")
    if metrics.get("critical_path"):
        lines.append(f"关键路径：{' → '.join(metrics['critical_path'])} "
                     f"（约 {metrics.get('critical_path_days')} 天）")
    if metrics.get("min_slack_days") is not None:
        lines.append(f"最小余量：{metrics['min_slack_days']} 天")
    lines.append(f"错误 {counts['errors']} 项，警告 {counts['warnings']} 项")

    if report["findings"]:
        lines.append("")
        for finding in report["findings"]:
            mark = "✗" if finding["level"] == "error" else "!"
            lines.append(f"{mark} [{finding['code']}] {finding['path']}")
            lines.append(f"   {finding['message']}")
            if finding["hint"]:
                lines.append(f"   → {finding['hint']}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="PlanWeaver 计划校验器：检查状态文件的自洽性与资源可行性")
    parser.add_argument("--state", required=True, help="plan-state.json 路径")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--strict", action="store_true", help="警告也视为失败（CI 用）")
    parser.add_argument("--out", help="将 JSON 报告写入指定文件")
    args = parser.parse_args(argv)

    try:
        with open(args.state, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        payload = {
            "ok": False, "verdict": "unknown", "counts": {"errors": 1, "warnings": 0},
            "findings": [{"level": "error", "code": "E_FILE", "path": args.state,
                          "message": "状态文件不存在", "hint": "先用 plan_tool.py init 建档，或确认路径"}],
            "metrics": {},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json"
              else f"错误：状态文件不存在（{args.state}）")
        return 2
    except json.JSONDecodeError as exc:
        payload = {
            "ok": False, "verdict": "unknown", "counts": {"errors": 1, "warnings": 0},
            "findings": [{"level": "error", "code": "E_JSON", "path": args.state,
                          "message": f"JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}",
                          "hint": "常见原因：多余逗号、引号未闭合、用了中文全角引号"}],
            "metrics": {},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.format == "json"
              else f"错误：JSON 解析失败（{exc.lineno}:{exc.colno} {exc.msg}）")
        return 2
    except OSError as exc:
        print(f"错误：无法读取文件（{exc}）", file=sys.stderr)
        return 2

    report = Validator(state).run()
    if args.strict:
        for finding in report["findings"]:
            if finding["level"] == "warning":
                finding["level"] = "error"
        report["counts"] = {
            "errors": sum(1 for f in report["findings"] if f["level"] == "error"),
            "warnings": sum(1 for f in report["findings"] if f["level"] == "warning"),
        }
        report["ok"] = report["counts"]["errors"] == 0

    if args.format == "text":
        print(render_text(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            print(f"警告：报告写入失败（{exc}）", file=sys.stderr)

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
