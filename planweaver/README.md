# PlanWeaver 全域智能规划师

> PlanWeaver Universal Planner — 在真实约束下协调多个目标的规划 Skill

PlanWeaver 帮用户把学习、工作、生活、长期目标放进**同一本资源账本**，算出这份计划在现实里到底能不能成立；当进度落后、临时加活、截止提前时，先做**影响分析**，只改真正受影响的部分。

它不是日程表生成器，也不是待办清单工具。它解决的是另外两个问题：**多个目标抢同一份时间时怎么协调**，以及**变化发生后怎么改计划才不把整张表推倒重来**。

---

## 一、解决什么问题

| 常见困境 | 普通做法 | PlanWeaver 的做法 |
|---|---|---|
| 学习、工作、生活各排一份计划 | 三份都"看起来合理"，合起来不可能执行 | 先汇总需求，再对一份总容量做判定 |
| "我想提高英语" | 直接给"每天背 50 词" | 先分清是考试/阅读/口语/写作，再编译成可验收目标 |
| "我落后三天了" | 把所有任务整体后移三天 | 算下游闭包，只动受影响的任务，其余冻结 |
| 时间明显不够 | 压缩睡眠、排满周末、"提高效率" | 如实报不可行，给四类出路让用户选 |
| 计划做完就废 | 没有偏差记录，下个月重复同样的错 | 记录预估 vs 实际，修正下一版估算 |

---

## 二、七种工作模式

| 模式 | 触发场景 | 输出 |
|---|---|---|
| A 全面规划 | 长期/复杂目标，需要整体路线 | 九段完整方案（目标→条件→可行性→三方案→推荐→路线图→近期清单→风险→更新方法） |
| B 快速决策 | "我现在该做什么" | 一个动作 + 理由 + 一个"先不做" |
| C 每日安排 | "今天/这周怎么排" | 时间块清单，留弹性 |
| D 进度更新 | "我做完了 X，花了 3 小时" | 状态更新 + 是否需要重排 |
| E 动态重规划 | 延期、突发任务、截止变化 | 七段重规划（变化→受影响→不变→可行性→方案→取舍→下一步） |
| F 目标冲突协调 | 两个目标抢同一份时间 | 2–3 种分配方式对比，让用户选 |
| G 阶段复盘 | 周/月/项目结束 | 计划 vs 实际 + 归因 + 下阶段调整 |

---

## 三、五项核心机制

1. **全域资源账本** — 学习/工作/生活共用一份时间池。有效可用 = 周可用 × (1 − 缓冲)，任务需求与之对比，输出"可行 / 紧张 / 不可行"三档判定。冲刺方案不是默认档。
2. **目标编译器** — 模糊愿望 → 目标名、成果、可验证的完成标准、截止与刚性、进度、前置、任务与依赖、三点估算、风险、下一步。
3. **多路径规划** — 保底 / 标准 / 冲刺三种方案，差异落在**目标范围与验收标准**上，而不是每天多排两小时。
4. **变化影响分析 + 动态重规划** — 算直接受影响、下游闭包、资源冲突，其余冻结；按 S0 吸收 → S1 重排 → S2 压缩 → S3 降级 → S4 延期 → S5 增资源/放弃 的阶梯逐级尝试。
5. **计划校准** — 记录实际 vs 预估，按任务类别算偏差系数；归因顺序从"拆分不合理/估算失真/前置缺失/资源冲突/外部事件"查起，最后才考虑执行波动。

---

## 四、安装

### 方式一：技能市场安装（正式发布后）

在 WorkBuddy 左侧菜单进入「专家 · 技能 · 连接器」→「技能」→ 搜索 **PlanWeaver** → 点加号安装。

### 方式二：导入 ZIP 包（当前可用）

1. 拿到 `planweaver-1.0.0.zip`
2. 在技能市场点右上角「添加技能」，选择导入 ZIP
3. 安装后在对话里说"帮我规划一下……"即可自动触发

### 方式三：本地目录

把整个 `planweaver/` 目录放到用户级技能目录：

```
~/.workbuddy-ai/skills/planweaver/
```

（Windows：`C:\Users\<你>\.workbuddy-ai\skills\planweaver\`）

---

## 五、调用方式

**自动触发**：描述里包含"规划/计划/排期/延期/落后了/时间不够/下一步做什么/复盘"等词时自动加载。

**显式调用**：

```
用 planweaver 帮我规划接下来三个月：雅思 6.5 + 项目交付 + 每周三次运动
```

```
用 planweaver 重排一下，我这周落后了三天
```

**直接说人话也行**，不需要记命令：

- 「我下周要出差三天，计划怎么改」
- 「考证和项目撞了，时间只够一个」
- 「这周复盘一下」

---

## 六、脚本

两个脚本，仅依赖 Python 标准库，无网络请求。

### 6.1 校验器

```bash
python scripts/validate_plan.py --state plan-state.json                 # JSON 报告
python scripts/validate_plan.py --state plan-state.json --format text   # 人读摘要
python scripts/validate_plan.py --state plan-state.json --strict        # 警告也算失败
```

退出码：`0` 通过 / `1` 有错误 / `2` 输入不可读。

**检查项**：字段与类型、枚举、id 唯一、引用完整、依赖环、三点估算顺序、前置与截止顺序、周容量超载、固定日程与任务块重叠、受保护时段被侵占、单日超 24 小时、进度自相矛盾、硬截止累计负荷、以及**重规划机械顺延检测**（用依赖图可达性判断被移动的任务是否真的受影响）。

**报告示例**：

```json
{
  "ok": true,
  "verdict": "tight",
  "counts": { "errors": 0, "warnings": 1 },
  "metrics": {
    "effort_likely": 6840,
    "effort_pessimistic": 9210,
    "effective_capacity": 9180.0,
    "utilization": 0.745,
    "critical_path": ["T1", "T2", "T5"],
    "critical_path_days": 12.4,
    "min_slack_days": 1.2
  }
}
```

### 6.2 状态管理

```bash
# 建档（生成 plan-state.json / plan-overview.md / change-log.md）
python scripts/plan_tool.py init --out ./my-plan --horizon-start 2026-10-19 --weeks 8 --weekly-minutes 900

# 更新进度（自动备份 + revision+1 + 追加 progress_log）
python scripts/plan_tool.py update --state ./my-plan/plan-state.json --task T2 --status done --actual 75

# 记录重规划（可同时平移受影响任务）
python scripts/plan_tool.py replan --state ./my-plan/plan-state.json \
  --trigger-type delay --description "评审延后 3 天" \
  --affected T3 --strategy S1 --moved T3,T5 --shift-days 3 --approved

# 新增任务
python scripts/plan_tool.py add-task --state ./my-plan/plan-state.json \
  --goal G1 --title "补充竞品对标" --likely 90 --week 2026-11-02

# 摘要 / 校验 / 导出
python scripts/plan_tool.py summary  --state ./my-plan/plan-state.json
python scripts/plan_tool.py validate --state ./my-plan/plan-state.json
python scripts/plan_tool.py export   --state ./my-plan/plan-state.json --out ./plan-export.json
```

---

## 七、状态文件与跨会话

三个文件：

| 文件 | 用途 |
|---|---|
| `plan-state.json` | 结构化状态，脚本读写，唯一事实源 |
| `plan-overview.md` | 人读概览（目标、账本、任务、风险） |
| `change-log.md` | 变更记录（含"未受影响的任务"承诺） |

**跨会话继续**：把 `plan-state.json` 放进对话或告诉路径即可。换设备时用 `export` 导出、在新会话导入。

**环境不支持写文件时**：Skill 会直接输出可复制的 JSON 与 Markdown，并明确说明"未保存"——不会假装写成功。

**数据安全**：所有状态都在你本地，不上传、不同步、不含账号信息。写入前自动备份到 `backups/`。

---

## 八、示例

**输入**：「我想三个月内把雅思考到 6.5，手上还有个项目 11 月中要交付，另外想每周运动三次。我每周大概能挤出 15 小时。」

**输出（节选）**：

```
有效可用 = 900 × (1 − 0.15) × 12 周 = 9,180 分钟
需求（通常）= 3,240 + 1,980 + 1,620 = 6,840 分钟（占用率 74%）
需求（保守）≈ 9,210 分钟

判定：紧张。可以按标准方案推进，但只能承诺保底成果，
且第 6 周必须检查一次——项目截止前 3 周会与雅思冲刺重叠。

推荐：标准方案 + 第 6 周检查点
放弃：雅思写作单项 6.5（只保总分 6.5）
不换的东西：睡眠 7.5 小时/天、每周半天无任务
```

完整案例见 `references/output-examples.md`（含延期重规划、多目标冲突、快速决策）。

---

## 九、已知限制

**能力边界**

1. **不接外部服务**：不读写日历、不发消息、不下单、不预约。所有输出都是可复制的文本/文件，需要你自己落到日历里。
2. **不替你决定优先级**：多目标冲突时给可比较的取舍，选择权在你。涉及放弃目标这类决定，必须你确认。
3. **估算仍是估算**：三点估算与偏差系数只能降低误差，不能消除。首次做的任务误差可能 ±50%，计划里会标明。
4. **校验器只判断自洽性**：它能算"时间够不够、依赖通不通、硬截止是否成立"，不能判断"这个目标值不值得"。动机、健康、家庭责任等由对话中的判断补充，且会标明是判断而非计算。
5. **关键路径是简化模型**：按任务工时求和折算天数，未计入并行任务争抢同一时段、固定日程的日历效应。用于排序与预警，不宜当作精确工期。
6. **单日冲突检测需要时间块**：任务只填到"周"时，只能校验周容量，无法检测具体时段撞车。要精确检测需提供 `blocks`（日期 + 起止时间）。
7. **不保存到云端**：状态文件在你本地，跨设备需手动导出/导入。

**刻意不做的事**

- 不生成精确到分钟的日程表（不确定性大时那是假精确）
- 不在资源不足时用"提高效率"充当方案
- 不把未完成任务整体顺延
- 不把延期归因为"你不够自律"

---

## 十、English Summary

PlanWeaver is a general-purpose planning skill. It puts learning, work, life, and long-term goals into **one resource ledger**, computes whether a plan is actually feasible under real time/energy constraints, and — when things change — performs **impact analysis** before touching the schedule, freezing everything that is not affected instead of rolling the whole plan forward.

Core mechanisms: unified resource ledger with a three-tier feasibility verdict (feasible / tight / infeasible); goal compiler that turns vague wishes into verifiable outcomes; three plan variants (baseline / standard / sprint) that differ in scope and acceptance criteria, not in hours per day; a six-level replanning ladder (absorb → reorder → compress → downgrade → extend → escalate); and calibration based on estimated-vs-actual records.

Two stdlib-only Python scripts provide deterministic checks (capacity, dependency cycles, deadline feasibility, mechanical-rollover detection) and portable state management (`plan-state.json`).

Out of scope in v1.0.0: no calendar/email/API integrations, no cloud sync, no decisions made on the user's behalf about life priorities.

---

## 十一、文件结构

```
planweaver/
├── SKILL.md                        # 技能定义（含四条红线、七种模式、输出契约）
├── README.md
├── CHANGELOG.md
├── LICENSE
├── references/
│   ├── planning-framework.md       # 资源账本、优先级、估算、容量、三方案
│   ├── replanning-playbook.md      # 变化分类、影响域、S0–S5 阶梯
│   ├── calibration.md              # 偏差系数、归因顺序、复盘结构
│   ├── state-schema.md             # 状态字段、枚举、错误码
│   └── output-examples.md          # 4 个完整案例 + 快速决策样例
├── scripts/
│   ├── validate_plan.py            # 确定性校验器
│   └── plan_tool.py                # 状态读写 CLI
├── templates/
│   ├── plan-state.json             # 可直接使用的状态骨架
│   ├── plan-overview.md
│   ├── weekly-plan.md
│   └── change-log.md
└── tests/                          # 单元测试 + 12 个场景测试（仅源码仓库，不随安装包分发）
```

> 安装包里只有 `SKILL.md` + `references/` + `scripts/` + `templates/` + `README/CHANGELOG/LICENSE`，
> 共 15 个文件。`tests/` 属于开发证据，官方结构未约定该目录，因此打包时默认剔除，
> 以免增加平台解析失败的风险。拿到源码目录时可运行 `python tests/run_tests.py`（105 项）。

---

## 十二、许可与作者

- **作者**：不会止步于此
- **许可证**：MIT License，见 `LICENSE`。使用时请保留版权与许可声明。

MIT 的含义用一句话说：**你可以随便用、改、卖，只要保留版权声明；作者不对使用后果负责。**

作者名称同时出现在 `SKILL.md` 的 `author` 字段、`LICENSE` 的著作权人、本文件与市场展示文案中，
四处必须一致（`tests/test_metadata.py` 会自动比对）。
