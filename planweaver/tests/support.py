# -*- coding: utf-8 -*-
"""测试支撑：状态构造器 + frontmatter 解析 + 运行辅助。仅用标准库。"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(TESTS_DIR)
SCRIPTS_DIR = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import validate_plan  # noqa: E402

PYTHON = sys.executable
VALIDATOR = os.path.join(SCRIPTS_DIR, "validate_plan.py")
TOOL = os.path.join(SCRIPTS_DIR, "plan_tool.py")

HORIZON_START = "2026-10-19"
HORIZON_END = "2026-12-13"


def week_start(index, start=HORIZON_START):
    """第 index 周（0 起）的周一日期，避免手写日期出错。"""
    import datetime
    return (datetime.date.fromisoformat(start) + datetime.timedelta(days=7 * index)).isoformat()


# --------------------------------------------------------------------------
# 状态构造
# --------------------------------------------------------------------------

def make_goal(gid="G1", **overrides):
    goal = {
        "id": gid,
        "name": f"目标 {gid}",
        "domain": "work",
        "outcome": "可交付的成果",
        "acceptance_criteria": ["成果通过验收"],
        "deadline": "2026-12-01",
        "deadline_rigidity": "soft",
        "weight": 3,
        "status": "active",
    }
    goal.update(overrides)
    return goal


def make_task(tid="T1", goal="G1", **overrides):
    task = {
        "id": tid,
        "goal_id": goal,
        "title": f"任务 {tid}",
        "estimate": {"optimistic": 60, "likely": 90, "pessimistic": 150},
        "depends_on": [],
        "scheduled": {"week_start": HORIZON_START, "minutes": 90, "slot": "上午"},
        "due": None,
        "status": "todo",
        "actual_minutes": 0,
        "completed_at": None,
        "compression_safe": False,
        "acceptance_criteria": ["完成且可验证"],
    }
    task.update(overrides)
    return task


def make_state(goals=None, tasks=None, weekly_minutes=900, buffer_ratio=0.15,
               fixed_events=None, protected_blocks=None, replans=None,
               horizon_start=HORIZON_START, horizon_end=HORIZON_END, **extra):
    state = {
        "schema_version": "1.0",
        "plan_id": "pw-test-001",
        "meta": {
            "created_at": "2026-10-19T09:00:00+08:00",
            "updated_at": "2026-10-19T09:00:00+08:00",
            "revision": 1,
            "timezone": "Asia/Shanghai",
            "horizon_start": horizon_start,
            "horizon_end": horizon_end,
            "active_variant": "standard",
            "title": "测试计划",
        },
        "constraints": {
            "capacity": {
                "weekly_minutes": weekly_minutes,
                "buffer_ratio": buffer_ratio,
                "energy_pattern": "高精力上午",
                "daily_capacity_minutes": None,
            },
            "budget": {"currency": "CNY", "total": 0, "note": ""},
            "fixed_events": fixed_events if fixed_events is not None else [],
            "protected_blocks": protected_blocks if protected_blocks is not None else [],
        },
        "goals": goals if goals is not None else [make_goal()],
        "tasks": tasks if tasks is not None else [make_task()],
        "variants": {
            "baseline": {"label": "保底", "scope": ["核心"], "dropped": ["拓展"]},
            "standard": {"label": "标准", "scope": ["核心", "拓展"], "dropped": []},
            "sprint": {"label": "冲刺", "scope": ["核心", "拓展", "加分"], "dropped": []},
        },
        "replans": replans if replans is not None else [],
        "progress_log": [],
        "calibration": {"samples": 0, "bias_by_category": {}, "notes": ""},
        "assumptions": [],
        "unknowns": [],
    }
    state.update(extra)
    return state


def make_replan(rid="R1", trigger_type="delay", affected=None, moved=None,
                strategy="S1", approved=True, description="测试变化", **extra):
    record = {
        "id": rid,
        "at": "2026-10-21T10:00:00+08:00",
        "trigger": {
            "type": trigger_type,
            "description": description,
            "affected_task_ids": affected if affected is not None else [],
            "delta_minutes": 0,
        },
        "moved_task_ids": moved if moved is not None else [],
        "strategy": strategy,
        "rejected_strategies": [],
        "approved_by_user": approved,
        "notes": "",
    }
    record.update(extra)
    return record


# --------------------------------------------------------------------------
# 运行辅助
# --------------------------------------------------------------------------

def run_validator(state, *args):
    """以子进程方式运行校验器，返回 (exit_code, payload_or_text)。"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "plan-state.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False)
        return _run([PYTHON, VALIDATOR, "--state", path, *args])


def run_tool(*args):
    return _run([PYTHON, TOOL, *args])


def _run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        payload = stdout + stderr
    return proc.returncode, payload


def validate(state):
    """进程内校验，返回 report dict（比子进程快，供多数测试使用）。"""
    return validate_plan.Validator(copy.deepcopy(state)).run()


def codes(report, level=None):
    return [f["code"] for f in report["findings"] if level is None or f["level"] == level]


def has_code(report, code):
    return code in codes(report)


# --------------------------------------------------------------------------
# frontmatter 解析（够用即可，不做完整 YAML）
# --------------------------------------------------------------------------

def parse_frontmatter(text):
    """解析 `---` 包围的简单 frontmatter：key: value，支持 > / | 折叠块。

    只支持本项目实际用到的子集。遇到无法解析的行直接抛错，避免"看起来通过了"。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("文件开头没有 --- 分隔符")
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        raise ValueError("frontmatter 没有结束的 ---")

    data = {}
    key = None
    buffer = []
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        if raw[0] in " \t":
            if key is None:
                raise ValueError(f"缩进出现在 key 之前：{raw!r}")
            buffer.append(raw.strip())
            continue
        if ":" not in raw:
            raise ValueError(f"无法解析的行（缺少冒号）：{raw!r}")
        if key is not None:
            data[key] = _finish(buffer)
            buffer = []
        name, _, value = raw.partition(":")
        key = name.strip()
        value = value.strip()
        if value in (">", "|", ">-", "|-"):
            buffer = []
            continue
        if value == "":
            buffer = []
            continue
        data[key] = value
        key = None
    if key is not None:
        data[key] = _finish(buffer)
    return data


def _finish(buffer):
    return " ".join(buffer).strip()
