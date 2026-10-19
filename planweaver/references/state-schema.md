# 状态文件规范（schema_version 1.0）

`plan-state.json` 是唯一事实源。`plan-overview.md` 和 `change-log.md` 是给人看的派生视图，不参与计算。

设计目标：**可移植**。一个 JSON 文件即全部状态，可复制、可导出、可跨会话导入，不依赖任何云端存储。

---

## 1. 顶层结构

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `schema_version` | string | ✅ | 固定 `"1.0"` |
| `plan_id` | string | 建议 | 计划标识，如 `pw-20261020-001` |
| `meta` | object | ✅ | 元信息，见 §2 |
| `constraints` | object | ✅ | 资源约束，见 §3 |
| `goals` | array | ✅ | 目标列表，见 §4（至少 1 条） |
| `tasks` | array | ✅ | 任务列表，见 §5（至少 1 条） |
| `variants` | object | 建议 | 三方案定义，见 §6 |
| `replans` | array | 建议 | 重规划记录，见 §7 |
| `progress_log` | array | 建议 | 进度流水，见 §8 |
| `calibration` | object | 可选 | 校准数据，见 §9 |
| `assumptions` | array | 建议 | 临时假设，见 §10 |
| `unknowns` | array | 可选 | 未知项，见 §10 |

**时间口径**：所有时间戳为带时区的 ISO 8601（`2026-10-20T09:00:00+08:00`）；所有日期为 `YYYY-MM-DD`；所有时段为 `HH:MM`（24 小时制）。时长单位统一为**分钟**（整数）。

---

## 2. meta

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `created_at` | string | ✅ | 创建时间 |
| `updated_at` | string | ✅ | 最后更新时间 |
| `revision` | int ≥ 1 | ✅ | 版本号，每次写入 +1 |
| `timezone` | string | 建议 | IANA 时区，如 `Asia/Shanghai` |
| `horizon_start` | date | ✅ | 计划起始日（建议为周一） |
| `horizon_end` | date | ✅ | 计划结束日，须晚于起始日 |
| `active_variant` | enum | ✅ | `baseline` / `standard` / `sprint` |
| `title` | string | 可选 | 计划标题 |

---

## 3. constraints

### 3.1 capacity

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `weekly_minutes` | int > 0 | ✅ | **真正可投入任务**的周分钟数（已排除睡眠与固定安排） |
| `buffer_ratio` | number 0–0.5 | ✅ | 缓冲比例，默认 `0.15` |
| `energy_pattern` | string | 可选 | 高/低精力时段描述，仅影响任务放置 |
| `daily_capacity_minutes` | int | 可选 | 日容量；缺省按 `weekly_minutes/7` 推算 |

### 3.2 fixed_events（不可移动）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✅ | 唯一 |
| `title` | string | ✅ | 名称 |
| `recurring` | bool | ✅ | 是否每周重复 |
| `weekday` | int 0–6 | 循环事件必填 | 0=周一 … 6=周日 |
| `date` | date | 单次事件必填 | 具体日期 |
| `start` / `end` | HH:MM | ✅ | 起止，`end` 须晚于 `start` |
| `rigid` | bool | 可选 | 默认 `true`（固定安排一律视为刚性） |

### 3.3 protected_blocks（必须保留）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✅ | 唯一 |
| `label` | string | ✅ | 如"睡眠""运动""家庭时间" |
| `daily_minutes` | int ≥ 0 | 与时段二选一 | 每日保留时长 |
| `start` / `end` | HH:MM | 与时长二选一 | 固定时段 |
| `rigid` | bool | 可选 | 默认 `true`；刚性时段不可被任务侵占 |

---

## 4. goals

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✅ | 唯一，建议 `G1` 形式 |
| `name` | string | ✅ | 目标名 |
| `domain` | enum | ✅ | `learning` / `work` / `life` / `health` / `finance` / `longterm` / `other` |
| `outcome` | string | 建议 | 预期成果 |
| `acceptance_criteria` | string[] | ✅ | 至少 1 条，可验证 |
| `deadline` | date \| null | ✅ | 截止日；`open` 刚性时可为 null |
| `deadline_rigidity` | enum | ✅ | `hard` / `soft` / `open` |
| `weight` | int 1–5 | ✅ | **用户给定**的重要度，模型不得代填 |
| `status` | enum | ✅ | `active` / `paused` / `done` / `abandoned` |
| `progress_note` | string | 可选 | 当前进度描述 |
| `prerequisites` | string[] | 可选 | 前置条件（资格、资料、他人配合） |
| `risks` | string[] | 可选 | 主要风险 |

---

## 5. tasks

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✅ | 唯一，建议 `T1` 形式 |
| `goal_id` | string | ✅ | 必须引用存在的 goal |
| `title` | string | ✅ | 具体动作，不是"做项目" |
| `estimate` | object | ✅ | `{optimistic, likely, pessimistic}`，均为 int > 0 且 `O ≤ M ≤ P` |
| `depends_on` | string[] | ✅ | 前置任务 id；可为空数组；不得自引用 |
| `scheduled` | object | ✅ | 见 §5.1 |
| `due` | date \| null | 可选 | 该任务截止 |
| `status` | enum | ✅ | `todo` / `doing` / `done` / `blocked` / `dropped` |
| `actual_minutes` | int ≥ 0 | 建议 | 实际耗时 |
| `completed_at` | string \| null | 可选 | 完成时间戳 |
| `priority` | int 1–5 | 可选 | 任务级优先级 |
| `compression_safe` | bool | 可选 | 是否允许 S2 压缩，默认 `false` |
| `acceptance_criteria` | string[] | 可选 | 任务级验收标准 |
| `blocks` | array | 可选 | 具体时间块，见 §5.1 |

### 5.1 scheduled / blocks

```json
"scheduled": { "week_start": "2026-10-20", "minutes": 90, "slot": "上午" }
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `week_start` | date | ✅ | 该任务落在哪一周（建议周一） |
| `minutes` | int ≥ 0 | ✅ | 本周分配时长 |
| `slot` | string | 可选 | `上午` / `下午` / `晚上` / 具体时段 |

可选 `blocks` 用于精确冲突检测（与固定日程、受保护时段比对）：

```json
"blocks": [{ "date": "2026-10-21", "start": "10:00", "end": "11:30" }]
```

**没有 `blocks` 时，只能做周容量校验，无法检测具体时段撞车。** 校验脚本会明确区分这两种精度。

---

## 6. variants

```json
"variants": {
  "baseline": {
    "label": "保底",
    "scope": ["核心成果 A"],
    "dropped": ["拓展任务 B", "加分项 C"],
    "buffer_ratio": 0.2,
    "capacity_minutes": 4200,
    "milestones": [{ "id": "M1", "title": "…", "due": "2026-11-15", "acceptance": "…" }]
  }
}
```

键必须是 `baseline` / `standard` / `sprint` 三者之一或全部。差异必须体现在 `scope` 与 `dropped` 上——只改 `capacity_minutes` 不算三种方案。

---

## 7. replans

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | ✅ | 如 `R1` |
| `at` | string | ✅ | 时间戳 |
| `trigger.type` | enum | ✅ | `delay` / `new_work` / `deadline_change` / `resource_change` / `scope_change` / `priority_change` / `abandon` / `early_completion` |
| `trigger.description` | string | ✅ | 变化事实 |
| `trigger.affected_task_ids` | string[] | ✅ | **直接**受影响的任务 |
| `trigger.delta_minutes` | int | 可选 | 延迟/新增工时（分钟） |
| `moved_task_ids` | string[] | ✅ | 实际被改动的任务 |
| `strategy` | enum | ✅ | `S0`–`S5` |
| `rejected_strategies` | string[] | 可选 | 试过但放弃的策略及原因写在 `notes` |
| `approved_by_user` | bool | ✅ | 用户是否确认 |
| `notes` | string | 建议 | 代价与风险说明 |

**校验逻辑**：`moved_task_ids` 必须是 `affected_task_ids` 的**下游闭包**（含自身）的子集。移动了闭包外的任务 → 触发 `W_ROLLOVER`（疑似机械顺延）。

---

## 8. progress_log

```json
{ "at": "2026-10-21T21:30:00+08:00", "task_id": "T1", "event": "done", "minutes": 75, "note": "比预估多 15 分钟" }
```

`event`：`started` / `done` / `partial` / `blocked` / `skipped` / `estimate_correction`。

---

## 9. calibration

```json
"calibration": {
  "samples": 6,
  "bias_by_category": { "writing": 1.4, "research": 1.15 },
  "notes": "写作类任务系统性低估 40%"
}
```

`samples < 3` 时不得据此给出偏差系数，只能提示趋势。

---

## 10. assumptions / unknowns

```json
"assumptions": [{ "id": "A1", "text": "每周可投入 15 小时", "confidence": "medium", "affects": "可行性判断" }],
"unknowns": [{ "id": "U1", "question": "考试具体日期？", "impact": "决定选保底还是标准方案" }]
```

---

## 11. 校验错误码

| 码 | 级别 | 含义 |
|---|---|---|
| `E_FILE` / `E_JSON` | error | 文件不可读 / JSON 解析失败（退出码 2） |
| `E_SCHEMA` | error | 缺必填字段或结构错误 |
| `E_TYPE` | error | 字段类型错误 |
| `E_ENUM` | error | 枚举值非法 |
| `E_DUP_ID` | error | id 重复 |
| `E_REF` | error | 引用不存在的 id |
| `E_CYCLE` | error | 依赖成环 |
| `E_ESTIMATE_ORDER` | error | 三点估算不满足 O ≤ M ≤ P |
| `E_DEP_DEADLINE` | error | 前置任务截止晚于后继任务 |
| `E_CAPACITY` | error | 某周任务量超过周可用时间 |
| `E_OVERLAP` | error | 任务时间块与固定日程重叠 |
| `E_PROTECTED` | error | 任务侵占受保护时段 |
| `E_PROGRESS` | error | 进度状态自相矛盾（如前置未完成却已完成） |
| `E_DEADLINE_INFEASIBLE` | error | 硬截止累计负荷超过可用容量 |
| `E_STRATEGY_HARD_DEADLINE_EXTEND` | error | S4（延长期限）被用在硬性截止目标上 |
| `E_DATE` | error | 日期/时段格式非法 |
| `W_TIGHT_WEEK` | warning | 某周占用超过有效容量但未超硬上限 |
| `W_GOAL_NO_DEADLINE` | warning | 目标无截止日期 |
| `W_DEADLINE_OUTSIDE` | warning | 硬截止超出计划窗口，无法校验可行性 |
| `W_NO_ACCEPTANCE` | warning | 缺可验证的完成标准 |
| `W_PROGRESS` | warning | 有实际耗时但状态未开始等轻微不一致 |
| `W_ESTIMATE_DRIFT` | warning | 实际耗时超过排期 2.5 倍，提示记入校准 |
| `W_ROLLOVER` | warning | 移动了不受影响的任务（疑似机械顺延） |
| `W_ROLLOVER_MASS` | warning | 大比例任务被同时移动（疑似整表后移） |
| `W_STRATEGY_MISMATCH` | warning | 策略与实际动作矛盾（如 S0 却移动了任务） |
| `W_COMPRESSION_UNSAFE` | warning | S2 压缩涉及未标记 `compression_safe` 的任务 |
| `W_NO_BUFFER` | warning | `buffer_ratio` 过低（< 0.05） |
| `W_VARIANT_MISSING` | warning | `active_variant` 在 `variants` 中没有定义 |
| `W_SCHEDULE_OUTSIDE` | warning | 任务排期超出计划窗口 |
| `W_NEGATIVE_SLACK` | warning | 按当前排期无法在任务截止日前完成（负余量） |
| `W_TASK_TOO_BIG` | warning | 单任务估算 > 240 分钟，建议拆分 |

`--strict` 模式下所有 warning 升级为 error（CI 用）。

---

## 12. 兼容与迁移

- 只认 `schema_version` 主版本；主版本不同 → `E_SCHEMA`，不做静默兼容。
- 未知字段**保留但忽略**，便于向前兼容；写回时不得丢弃未知字段（`plan_tool.py` 保留原始键）。
- 导出 = 原样复制 JSON；导入 = 校验后写入，校验失败不覆盖现有文件。
