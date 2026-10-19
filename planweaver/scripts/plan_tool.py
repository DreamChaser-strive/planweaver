#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PlanWeaver 状态管理工具（仅依赖 Python 标准库）。

子命令:
    init      建立初始状态三件套（plan-state.json / plan-overview.md / change-log.md）
    update    更新任务进度（自动备份 + 追加 progress_log + revision+1）
    replan    记录一次重规划，可同时平移受影响任务的排期
    add-task  新增任务
    summary   输出人读摘要（含容量与可行性判定）
    validate  调用 validate_plan.py 校验
    export    导出状态文件（用于跨会话 / 跨设备迁移）

设计原则:
    - 写前必备份，绝不静默覆盖
    - 保留未知字段，不因工具版本落后而丢用户数据
    - 只做确定性操作，不做"智能改写"（判断留给 Agent）
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import validate_plan  # noqa: E402  (同目录模块)

SKILL_ROOT = os.path.dirname(HERE)
TEMPLATE_DIR = os.path.join(SKILL_ROOT, "templates")
TOOL_VERSION = "1.0.0"


# --------------------------------------------------------------------------
# 通用
# --------------------------------------------------------------------------

def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def die(message, code=2):
    print(f"错误：{message}", file=sys.stderr)
    sys.exit(code)


def load_state(path):
    if not os.path.isfile(path):
        die(f"状态文件不存在：{path}\n提示：先用 init 建档，或确认路径是否正确")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except json.JSONDecodeError as exc:
        die(f"JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}")
    if not isinstance(state, dict):
        die("状态文件顶层必须是 JSON 对象")
    return state


def backup(path):
    directory = os.path.dirname(os.path.abspath(path))
    backup_dir = os.path.join(directory, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.splitext(os.path.basename(path))[0]
    target = os.path.join(backup_dir, f"{base}.{stamp}.json")
    shutil.copy2(path, target)
    return target


def save_state(path, state, skip_backup=False, strict_write=False):
    """原子写入。返回 (备份路径 or None, 校验报告)。"""
    report = validate_plan.Validator(state).run()
    if strict_write and not report["ok"]:
        codes = ", ".join(sorted({f["code"] for f in report["findings"] if f["level"] == "error"}))
        die(f"写入被拒绝（--strict-write）：新状态存在错误 {codes}\n"
            f"先修复再写入，或用 validate 查看详情", code=1)

    saved_backup = None
    if os.path.isfile(path) and not skip_backup:
        saved_backup = backup(path)

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    return saved_backup, report


def bump(state):
    meta = state.setdefault("meta", {})
    revision = meta.get("revision")
    meta["revision"] = (revision if isinstance(revision, int) and revision >= 1 else 0) + 1
    meta["updated_at"] = now_iso()
    return meta["revision"]


def find_task(state, task_id):
    for task in state.get("tasks", []):
        if task.get("id") == task_id:
            return task
    return None


def find_goal(state, goal_id):
    for goal in state.get("goals", []):
        if goal.get("id") == goal_id:
            return goal
    return None


def split_ids(value):
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_date_arg(value, label):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        die(f"{label} 必须是 YYYY-MM-DD，当前为 {value!r}")


def print_report_brief(report):
    verdict_zh = {"feasible": "可行", "tight": "紧张", "infeasible": "不可行"}.get(
        report["verdict"], report["verdict"])
    counts = report["counts"]
    print(f"校验：{'通过' if report['ok'] else '未通过'} | 可行性判定：{verdict_zh} | "
          f"错误 {counts['errors']} | 警告 {counts['warnings']}")
    for finding in report["findings"]:
        if finding["level"] == "error":
            print(f"  ✗ [{finding['code']}] {finding['path']} — {finding['message']}")
    for finding in report["findings"]:
        if finding["level"] == "warning":
            print(f"  ! [{finding['code']}] {finding['path']} — {finding['message']}")


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------

def cmd_init(args):
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)
    state_path = os.path.join(out_dir, "plan-state.json")
    if os.path.isfile(state_path) and not args.force:
        die(f"{state_path} 已存在。为避免覆盖你的计划，请加 --force 或换一个目录")

    template_path = os.path.join(TEMPLATE_DIR, "plan-state.json")
    if not os.path.isfile(template_path):
        die(f"模板缺失：{template_path}")
    with open(template_path, "r", encoding="utf-8") as handle:
        state = json.load(handle)

    start = parse_date_arg(args.horizon_start, "--horizon-start")
    weeks = args.weeks
    if weeks < 1:
        die("--weeks 必须 ≥ 1")
    end = start + datetime.timedelta(days=weeks * 7 - 1)

    meta = state.setdefault("meta", {})
    meta["horizon_start"] = start.isoformat()
    meta["horizon_end"] = end.isoformat()
    meta["created_at"] = now_iso()
    meta["updated_at"] = meta["created_at"]
    meta["revision"] = 1
    meta["title"] = args.title or meta.get("title", "我的计划")
    state["plan_id"] = f"pw-{start.strftime('%Y%m%d')}-001"

    capacity = state.setdefault("constraints", {}).setdefault("capacity", {})
    capacity["weekly_minutes"] = args.weekly_minutes
    if args.buffer_ratio is not None:
        capacity["buffer_ratio"] = args.buffer_ratio

    saved_backup, report = save_state(state_path, state, skip_backup=True, strict_write=False)
    print(f"已建立状态文件：{state_path}")
    print(f"计划窗口：{start} → {end}（{weeks} 周）")
    print(f"周可用：{args.weekly_minutes} 分钟 | 缓冲：{capacity.get('buffer_ratio')}")

    overview_path = os.path.join(out_dir, "plan-overview.md")
    changelog_path = os.path.join(out_dir, "change-log.md")
    write_overview(overview_path, state)
    write_changelog(changelog_path, state)
    print(f"已生成概览：{overview_path}")
    print(f"已生成变更记录：{changelog_path}")
    print_report_brief(report)
    print("\n下一步：模板里的目标与任务是示例，请替换成你自己的；"
          "替换后运行 validate 再开始执行。")
    return 0 if report["ok"] else 1


def write_overview(path, state):
    template_path = os.path.join(TEMPLATE_DIR, "plan-overview.md")
    with open(template_path, "r", encoding="utf-8") as handle:
        text = handle.read()
    meta = state.get("meta", {})
    capacity = state.get("constraints", {}).get("capacity", {})
    weekly = capacity.get("weekly_minutes", 0)
    ratio = capacity.get("buffer_ratio", 0) or 0
    start = meta.get("horizon_start", "")
    end = meta.get("horizon_end", "")
    weeks = 0
    try:
        weeks = max(1, round((datetime.date.fromisoformat(end)
                              - datetime.date.fromisoformat(start)).days / 7))
    except (TypeError, ValueError):
        pass
    effective_week = weekly * (1 - ratio)
    replacements = {
        "{{PLAN_TITLE}}": str(meta.get("title", "我的计划")),
        "{{HORIZON_START}}": str(start),
        "{{HORIZON_END}}": str(end),
        "{{ACTIVE_VARIANT}}": str(meta.get("active_variant", "standard")),
        "{{REVISION}}": str(meta.get("revision", 1)),
        "{{UPDATED_AT}}": str(meta.get("updated_at", "")),
        "{{WEEKLY_MINUTES}}": str(weekly),
        "{{EFFECTIVE_WEEK}}": f"{effective_week:.0f}",
        "{{WEEKS}}": str(weeks),
        "{{EFFECTIVE_TOTAL}}": f"{effective_week * weeks:.0f}",
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    text = ("> ⚠️ 本文件由 plan_tool.py 从模板生成，正文中的示例目标/任务/数字需要你替换。\n"
            "> 结构化数据以 plan-state.json 为准；本文件是给人看的视图。\n\n") + text
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def write_changelog(path, state):
    meta = state.get("meta", {})
    header = f"""# 计划变更记录

- 计划：{meta.get('title', '我的计划')}
- 计划 ID：{state.get('plan_id', '')}
- 窗口：{meta.get('horizon_start', '')} → {meta.get('horizon_end', '')}
- 建档时间：{meta.get('created_at', '')}

> 只记重要变更：影响排期、范围、验收标准、优先级、资源约束的动作。
> 每次记录必须写清「为什么改」。

---

## {str(meta.get('created_at', ''))[:10]} · 建立计划（v1）

- **类型**：`init`
- **事实**：按 {meta.get('horizon_start', '')} → {meta.get('horizon_end', '')} 建立初始计划。
- **策略**：不适用（首次建档）
- **用户确认**：是

---

"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(header)


# --------------------------------------------------------------------------
# update
# --------------------------------------------------------------------------

def cmd_update(args):
    state = load_state(args.state)
    task = find_task(state, args.task)
    if task is None:
        die(f"找不到任务 {args.task}。可用任务："
            f"{', '.join(t.get('id', '?') for t in state.get('tasks', []))}")

    changes = []
    old_status = task.get("status")
    if args.status:
        if args.status not in validate_plan.TASK_STATUS:
            die(f"--status 必须是 {sorted(validate_plan.TASK_STATUS)} 之一")
        task["status"] = args.status
        if args.status != old_status:
            changes.append(f"状态 {old_status} → {args.status}")
    if args.actual is not None:
        if args.actual < 0:
            die("--actual 不能为负")
        task["actual_minutes"] = args.actual
        changes.append(f"实际耗时 {args.actual} 分钟")
    if args.add_actual is not None:
        if args.add_actual < 0:
            die("--add-actual 不能为负")
        task["actual_minutes"] = (task.get("actual_minutes") or 0) + args.add_actual
        changes.append(f"累加实际耗时 {args.add_actual} 分钟（合计 {task['actual_minutes']}）")
    if args.due:
        task["due"] = parse_date_arg(args.due, "--due").isoformat()
        changes.append(f"截止改为 {task['due']}")
    if args.week:
        week = parse_date_arg(args.week, "--week").isoformat()
        task.setdefault("scheduled", {})["week_start"] = week
        changes.append(f"排期周改为 {week}")
    if args.minutes is not None:
        if args.minutes < 0:
            die("--minutes 不能为负")
        task.setdefault("scheduled", {})["minutes"] = args.minutes
        changes.append(f"本周分配 {args.minutes} 分钟")

    if not changes:
        die("没有要修改的内容。至少提供 --status / --actual / --add-actual / --due / --week / --minutes 之一")

    if task.get("status") == "done" and not task.get("completed_at"):
        task["completed_at"] = now_iso()
        if not task.get("actual_minutes"):
            print("提示：任务标记完成但没有实际耗时，校准将缺少数据。建议补 --actual。")

    event = "done" if task.get("status") == "done" else (
        "started" if task.get("status") == "doing" else "partial")
    if args.status is None:
        event = "estimate_correction"
    state.setdefault("progress_log", []).append({
        "at": now_iso(),
        "task_id": args.task,
        "event": event,
        "minutes": task.get("actual_minutes") or 0,
        "note": args.note or "；".join(changes),
    })

    revision = bump(state)
    saved_backup, report = save_state(args.state, state, strict_write=args.strict_write)

    print(f"已更新 {args.task}：" + "；".join(changes))
    print(f"版本：v{revision}" + (f" | 备份：{saved_backup}" if saved_backup else ""))
    print_report_brief(report)
    print("\n提示：若任务延期或状态变化会影响下游任务，请用 replan 记录影响分析与调整，"
          "不要直接改后续任务排期。")
    return 0 if report["ok"] else 1


# --------------------------------------------------------------------------
# replan
# --------------------------------------------------------------------------

def cmd_replan(args):
    state = load_state(args.state)
    affected = split_ids(args.affected)
    moved = split_ids(args.moved)

    for tid in affected:
        if find_task(state, tid) is None:
            die(f"受影响任务 {tid} 不存在")
    for tid in moved:
        if find_task(state, tid) is None:
            die(f"被移动任务 {tid} 不存在")
    if args.trigger_type not in validate_plan.TRIGGER_TYPES:
        die(f"--trigger-type 必须是 {sorted(validate_plan.TRIGGER_TYPES)} 之一")
    if args.strategy not in validate_plan.STRATEGIES:
        die("--strategy 必须是 S0–S5 之一")

    shifted = []
    if args.shift_days:
        if not moved:
            die("--shift-days 需要同时用 --moved 指定要平移的任务")
        delta = datetime.timedelta(days=args.shift_days)
        for tid in moved:
            task = find_task(state, tid)
            scheduled = task.setdefault("scheduled", {})
            try:
                week = datetime.date.fromisoformat(scheduled["week_start"])
                scheduled["week_start"] = (week + delta).isoformat()
            except (KeyError, TypeError, ValueError):
                pass
            if task.get("due"):
                try:
                    due = datetime.date.fromisoformat(task["due"])
                    task["due"] = (due + delta).isoformat()
                except ValueError:
                    pass
            shifted.append(tid)

    record = {
        "id": f"R{len(state.get('replans', [])) + 1}",
        "at": now_iso(),
        "trigger": {
            "type": args.trigger_type,
            "description": args.description,
            "affected_task_ids": affected,
            "delta_minutes": args.delta_minutes or 0,
        },
        "moved_task_ids": moved,
        "strategy": args.strategy,
        "rejected_strategies": split_ids(args.rejected),
        "approved_by_user": bool(args.approved),
        "notes": args.notes or "",
    }
    state.setdefault("replans", []).append(record)
    revision = bump(state)
    saved_backup, report = save_state(args.state, state, strict_write=args.strict_write)

    print(f"已记录重规划 {record['id']}：{args.trigger_type} / {args.strategy}"
          + (f"，平移任务 {', '.join(shifted)}" if shifted else ""))
    print(f"版本：v{revision}" + (f" | 备份：{saved_backup}" if saved_backup else ""))
    print_report_brief(report)

    print("\n提醒：请把同样的内容追加到 change-log.md，包括"
          "「未受影响、保持不变」的任务清单——那是对用户的承诺。")
    return 0 if report["ok"] else 1


# --------------------------------------------------------------------------
# add-task
# --------------------------------------------------------------------------

def cmd_add_task(args):
    state = load_state(args.state)
    if find_goal(state, args.goal) is None:
        die(f"目标 {args.goal} 不存在。可用目标："
            f"{', '.join(g.get('id', '?') for g in state.get('goals', []))}")

    tasks = state.setdefault("tasks", [])
    if args.id:
        if find_task(state, args.id):
            die(f"任务 id {args.id} 已存在")
        tid = args.id
    else:
        numbers = [int(t["id"][1:]) for t in tasks
                   if isinstance(t.get("id"), str) and t["id"].startswith("T") and t["id"][1:].isdigit()]
        tid = f"T{max(numbers) + 1 if numbers else 1}"

    optimistic = args.optimistic if args.optimistic is not None else args.likely
    pessimistic = args.pessimistic if args.pessimistic is not None else args.likely
    if not (optimistic <= args.likely <= pessimistic):
        die("必须满足 optimistic ≤ likely ≤ pessimistic")

    week = parse_date_arg(args.week, "--week").isoformat() if args.week else \
        state.get("meta", {}).get("horizon_start")
    due = parse_date_arg(args.due, "--due").isoformat() if args.due else None

    task = {
        "id": tid,
        "goal_id": args.goal,
        "title": args.title,
        "estimate": {
            "optimistic": optimistic,
            "likely": args.likely,
            "pessimistic": pessimistic,
        },
        "depends_on": split_ids(args.depends),
        "scheduled": {
            "week_start": week,
            "minutes": args.minutes if args.minutes is not None else args.likely,
            "slot": args.slot or "",
        },
        "due": due,
        "status": "todo",
        "actual_minutes": 0,
        "completed_at": None,
        "priority": args.priority,
        "compression_safe": bool(args.compression_safe),
        "acceptance_criteria": split_ids(args.acceptance),
    }
    tasks.append(task)
    revision = bump(state)
    saved_backup, report = save_state(args.state, state, strict_write=args.strict_write)

    print(f"已新增任务 {tid}：{args.title}（{args.likely} 分钟，排期 {week}）")
    print(f"版本：v{revision}" + (f" | 备份：{saved_backup}" if saved_backup else ""))
    print_report_brief(report)
    return 0 if report["ok"] else 1


# --------------------------------------------------------------------------
# summary / validate / export
# --------------------------------------------------------------------------

def cmd_summary(args):
    state = load_state(args.state)
    report = validate_plan.Validator(state).run()
    meta = state.get("meta", {})
    metrics = report["metrics"]

    print(f"计划：{meta.get('title', '（未命名）')}  v{meta.get('revision')}")
    print(f"窗口：{meta.get('horizon_start')} → {meta.get('horizon_end')} | "
          f"方案：{meta.get('active_variant')}")
    print("")
    print("目标")
    for goal in state.get("goals", []):
        print(f"  [{goal.get('id')}] {goal.get('name')} | {goal.get('domain')} | "
              f"截止 {goal.get('deadline')} ({goal.get('deadline_rigidity')}) | "
              f"权重 {goal.get('weight')} | {goal.get('status')}")
    print("")
    print("任务")
    for task in state.get("tasks", []):
        estimate = task.get("estimate", {})
        print(f"  [{task.get('id')}] {task.get('title')} | "
              f"{estimate.get('likely')}min | {task.get('status')} | "
              f"排期 {(task.get('scheduled') or {}).get('week_start')} | "
              f"依赖 {','.join(task.get('depends_on') or []) or '—'}")
    print("")
    print("资源")
    if metrics.get("effective_capacity"):
        print(f"  有效容量 {metrics['effective_capacity']:.0f} 分钟 | "
              f"需求(通常) {metrics['effort_likely']} | 需求(保守) {metrics['effort_pessimistic']} | "
              f"占用率 {(metrics.get('utilization') or 0):.0%}")
    if metrics.get("critical_path"):
        print(f"  关键路径 {' → '.join(metrics['critical_path'])} "
              f"（约 {metrics.get('critical_path_days')} 天）")
    if metrics.get("min_slack_days") is not None:
        print(f"  最小余量 {metrics['min_slack_days']} 天")
    print("")
    print_report_brief(report)
    return 0 if report["ok"] else 1


def cmd_validate(args):
    report = validate_plan.Validator(load_state(args.state)).run()
    if args.format == "text":
        print(validate_plan.render_text(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def cmd_export(args):
    state = load_state(args.state)
    report = validate_plan.Validator(state).run()
    out = args.out
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"已导出：{out}")
    print(f"校验：{'通过' if report['ok'] else '未通过'}（错误 {report['counts']['errors']}）")
    if not report["ok"]:
        print("提示：导出的文件带有错误，换会话导入后应先修复再排期。")
    return 0 if report["ok"] else 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="plan_tool.py",
        description="PlanWeaver 状态管理：建档、更新进度、记录重规划、导出迁移")
    parser.add_argument("--version", action="version", version=f"planweaver-tool {TOOL_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="建立初始状态三件套")
    p_init.add_argument("--out", required=True, help="输出目录")
    p_init.add_argument("--horizon-start", required=True, help="计划起始日 YYYY-MM-DD（建议周一）")
    p_init.add_argument("--weeks", type=int, default=8, help="计划周数，默认 8")
    p_init.add_argument("--weekly-minutes", type=int, default=900,
                        help="每周可投入任务的分钟数，默认 900（15 小时）")
    p_init.add_argument("--buffer-ratio", type=float, default=None, help="缓冲比例，默认沿用模板 0.15")
    p_init.add_argument("--title", default=None, help="计划标题")
    p_init.add_argument("--force", action="store_true", help="覆盖已存在的状态文件（会先备份）")
    p_init.set_defaults(func=cmd_init)

    p_update = sub.add_parser("update", help="更新任务进度")
    p_update.add_argument("--state", required=True)
    p_update.add_argument("--task", required=True, help="任务 id，如 T2")
    p_update.add_argument("--status", help="todo / doing / done / blocked / dropped")
    p_update.add_argument("--actual", type=int, help="设置实际耗时（分钟）")
    p_update.add_argument("--add-actual", type=int, dest="add_actual", help="累加实际耗时（分钟）")
    p_update.add_argument("--due", help="修改截止日 YYYY-MM-DD")
    p_update.add_argument("--week", help="修改排期周 YYYY-MM-DD")
    p_update.add_argument("--minutes", type=int, help="修改本周分配分钟数")
    p_update.add_argument("--note", help="备注")
    p_update.add_argument("--strict-write", action="store_true", help="新状态有 error 时拒绝写入")
    p_update.set_defaults(func=cmd_update)

    p_replan = sub.add_parser("replan", help="记录一次重规划")
    p_replan.add_argument("--state", required=True)
    p_replan.add_argument("--trigger-type", required=True, dest="trigger_type",
                          help="delay / new_work / deadline_change / resource_change / "
                               "scope_change / priority_change / abandon / early_completion")
    p_replan.add_argument("--description", required=True, help="变化事实（一句话）")
    p_replan.add_argument("--affected", help="直接受影响的任务 id，逗号分隔")
    p_replan.add_argument("--strategy", required=True, help="S0 / S1 / S2 / S3 / S4 / S5")
    p_replan.add_argument("--moved", help="实际被移动的任务 id，逗号分隔")
    p_replan.add_argument("--shift-days", type=int, dest="shift_days", help="同时平移这些任务的排期与截止（天）")
    p_replan.add_argument("--delta-minutes", type=int, dest="delta_minutes", help="延迟/新增工时（分钟）")
    p_replan.add_argument("--rejected", help="试过但放弃的策略，逗号分隔，如 S0,S2")
    p_replan.add_argument("--notes", help="代价与风险说明")
    p_replan.add_argument("--approved", action="store_true", help="用户已确认")
    p_replan.add_argument("--strict-write", action="store_true")
    p_replan.set_defaults(func=cmd_replan)

    p_add = sub.add_parser("add-task", help="新增任务")
    p_add.add_argument("--state", required=True)
    p_add.add_argument("--goal", required=True, help="所属目标 id")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--likely", type=int, required=True, help="通常估算（分钟）")
    p_add.add_argument("--optimistic", type=int, default=None)
    p_add.add_argument("--pessimistic", type=int, default=None)
    p_add.add_argument("--week", help="排期周起始日 YYYY-MM-DD")
    p_add.add_argument("--minutes", type=int, default=None, help="本周分配分钟数，默认等于 likely")
    p_add.add_argument("--depends", help="前置任务 id，逗号分隔")
    p_add.add_argument("--due", help="截止日 YYYY-MM-DD")
    p_add.add_argument("--id", help="自定义任务 id，默认自动 T{n}")
    p_add.add_argument("--slot", help="时间块，如 上午")
    p_add.add_argument("--priority", type=int, default=None)
    p_add.add_argument("--compression-safe", action="store_true", dest="compression_safe")
    p_add.add_argument("--acceptance", help="验收标准，逗号分隔")
    p_add.add_argument("--strict-write", action="store_true")
    p_add.set_defaults(func=cmd_add_task)

    p_summary = sub.add_parser("summary", help="输出人读摘要")
    p_summary.add_argument("--state", required=True)
    p_summary.set_defaults(func=cmd_summary)

    p_validate = sub.add_parser("validate", help="校验状态文件")
    p_validate.add_argument("--state", required=True)
    p_validate.add_argument("--format", choices=("json", "text"), default="text")
    p_validate.set_defaults(func=cmd_validate)

    p_export = sub.add_parser("export", help="导出状态文件")
    p_export.add_argument("--state", required=True)
    p_export.add_argument("--out", required=True)
    p_export.set_defaults(func=cmd_export)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
