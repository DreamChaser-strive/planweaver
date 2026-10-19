# PlanWeaver 全域智能规划师

> 把学习、工作、生活放进同一本时间账本，先算清到底做不做得到，再排计划；情况变了，只改真正受影响的部分。

这是 [PlanWeaver](planweaver/) 的完整源码与发布工程，一个面向 WorkBuddy 的 Skill。

**它不是日程表生成器。** 核心是两件事：

1. **跨领域资源协调** —— 所有目标争夺同一份时间，必须一起算总账；
2. **变化影响分析 + 定向重规划** —— 变化发生后冻结不受影响的部分，只重排受影响的链条。

---

## 目录结构

```
.
├── planweaver/                 # Skill 源码（可安装的那部分）
│   ├── SKILL.md                # 技能定义：四条红线、七种模式、输出契约
│   ├── references/             # 5 篇方法论文档（资源账本 / 重规划 / 校准 / 状态 / 案例）
│   ├── scripts/                # 2 个纯标准库脚本（校验器 + 状态工具）
│   ├── templates/              # 4 个可直接使用的模板
│   └── tests/                  # 105 项自动化测试
├── tools/
│   ├── build_release.py        # 构建：校验元数据 → 跑测试 → 写作者 → 打 ZIP
│   ├── audit_package.py        # 审计：对 ZIP 做 34 项只读检查
│   └── make_avatar.py          # 纯标准库绘制 512×512 头像
├── release/                    # 发布材料（市场文案、验收清单、测试报告、审计报告）
└── dist/                       # 构建产物，不入库
```

---

## 快速开始

### 安装到 WorkBuddy

```bash
# 方式一：构建 ZIP 后从客户端「添加技能」导入
python tools/build_release.py --author "你的名字"

# 方式二：直接放进用户技能目录
cp -r planweaver ~/.workbuddy-ai/skills/
```

安装后直接说人话即可触发：`帮我规划一下接下来三个月`。

### 开发与验证

```bash
cd planweaver
python tests/run_tests.py          # 105 项测试
```

### 构建发布包

```bash
python tools/build_release.py --author "你的名字" --both
python tools/audit_package.py --zip dist/planweaver-1.0.0.zip
```

`--author` 会把名字同时写进 `SKILL.md` / `LICENSE` / `README.md` / `release/MARKETING.md`，
并自检四处一致；`--update-source` 可一并写回源码；`--flat` 生成扁平包。

---

## 这个 Skill 做什么

| 模式 | 触发场景 | 输出 |
|---|---|---|
| A 全面规划 | 长期/复杂目标 | 九段完整方案（含有效容量 vs 需求的具体数字） |
| B 快速决策 | "我现在该做什么" | 一个动作 + 理由 + 一个"先不做" |
| C 每日安排 | "今天怎么排" | 时间块清单，留弹性 |
| D 进度更新 | "我做完了 X" | 状态更新 + 是否触发重排 |
| E 动态重规划 | 延期、突发、截止变化 | 七段重规划（含"哪些不变"的承诺） |
| F 目标冲突协调 | 两个目标抢同一份时间 | 2–3 种分配方式对比 |
| G 阶段复盘 | 周/月/项目结束 | 计划 vs 实际 + 归因 + 下阶段调整 |

**五项核心机制**：全域资源账本 · 目标编译器 · 保底/标准/冲刺三方案 · 变化影响分析与六级策略阶梯 · 计划校准。

最直观的差别：当你说"我落后三天了"，它不会把整张表后移三天——它会先算下游闭包和余量，
余量够就告诉你**不用改计划**，并把"哪些安排不变"逐条列出来。

---

## 已知限制

- 不接日历 / 邮件 / 第三方 API，不写回任何外部系统
- 不做自动监控、不做主动提醒、不做跨设备同步
- 关键路径为简化模型（工时求和折算天数），用于排序与预警，不是精确工期
- 任务只填到"周"时只能校验周容量；检测具体时段冲突需提供时间块

---

## 状态

`1.0.0` 为待发布版本：自动化测试与包审计已通过，客户端人工验收与平台审核尚未进行。
详见 [release/TEST-REPORT.md](release/TEST-REPORT.md) 与 [release/ACCEPTANCE-TESTS.md](release/ACCEPTANCE-TESTS.md)。

---

## 许可

MIT License，见 [LICENSE](planweaver/LICENSE)。可自由使用、修改、商用，保留版权声明即可。

作者：**不会止步于此**
