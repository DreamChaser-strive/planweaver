# PlanWeaver 发布包审计报告

- 审计对象：`dist/planweaver-1.0.0.zip`
- 审计时间：2026-10-20
- 审计工具：`tools/audit_package.py`（只读，仅标准库）
- 复现命令：`python tools/audit_package.py --zip dist/planweaver-1.0.0.zip`
- 工具退出码：0（0 全部通过 / 1 存在失败项）
- 结论：**通过**。唯一警告是 `category` 需在后台确认，不影响提交。

> 本文件由审计工具输出直接生成，不是手写结论。

---

```
PlanWeaver 发布包审计：通过
检查项 34 个 | 通过 33 | 警告 1 | 失败 0

一、文件清单
      字节  路径
    4746  planweaver/CHANGELOG.md
    1615  planweaver/LICENSE
   12908  planweaver/README.md
   19797  planweaver/SKILL.md
    5138  planweaver/references/calibration.md
   11112  planweaver/references/output-examples.md
   11060  planweaver/references/planning-framework.md
   10241  planweaver/references/replanning-playbook.md
   10850  planweaver/references/state-schema.md
   26796  planweaver/scripts/plan_tool.py
   60909  planweaver/scripts/validate_plan.py
    2994  planweaver/templates/change-log.md
    3101  planweaver/templates/plan-overview.md
    6299  planweaver/templates/plan-state.json
    1801  planweaver/templates/weekly-plan.md
  189367  合计 15 个文件

二、逐项检查
✓ [文件清单] 共 15 个文件，解压后合计 189,367 字节（184.9 KB）
✓ [目录结构] 单顶层目录 planweaver/，SKILL.md 在目录根（与官方结构图一致）
✓ [必需文件] SKILL.md 存在（9,545 字符）
✓ [必需文件] README.md 存在（7,526 字符）
✓ [必需文件] CHANGELOG.md 存在（2,300 字符）
✓ [必需文件] LICENSE 存在（1,283 字符）
✓ [frontmatter] 可解析，共 9 个字段
✓ [frontmatter] name = planweaver
✓ [frontmatter] description = 全域智能规划师。当用户要制定、调整或诊断跨学习/工作/生活/长期目标的计划时使用
✓ [frontmatter] description_zh = 协调学习、工作、生活与长期目标，在真实时间与精力约束下制定可执行计划，并在延期、
✓ [frontmatter] description_en = A general-purpose planning skill that co
✓ [frontmatter] version = 1.0.0
✓ [frontmatter] author = 不会止步于此
✓ [frontmatter] category = capability
! [frontmatter] category=capability（官方文档未公布枚举，需在后台确认）
    → 后台分类选择以页面选项为准
✓ [引用完整性] @references/calibration.md 可解析
✓ [引用完整性] @references/output-examples.md 可解析
✓ [引用完整性] @references/planning-framework.md 可解析
✓ [引用完整性] @references/replanning-playbook.md 可解析
✓ [引用完整性] @references/state-schema.md 可解析
✓ [引用完整性] @templates/change-log.md 可解析
✓ [引用完整性] @templates/plan-overview.md 可解析
✓ [引用完整性] @templates/plan-state.json 可解析
✓ [引用完整性] @templates/weekly-plan.md 可解析
✓ [references/] 5 个文件：calibration.md, output-examples.md, planning-framework.md, replanning-playbook.md, state-schema.md
✓ [scripts/] 2 个文件：plan_tool.py, validate_plan.py
✓ [templates/] 4 个文件：change-log.md, plan-overview.md, plan-state.json, weekly-plan.md
✓ [内容合规] 无 TODO/FIXME/待补充
✓ [内容合规] 无密钥/token/密码样式字符串
✓ [内容合规] 无邮箱地址
✓ [内容合规] 无手机号样式数字
✓ [依赖] 所有脚本仅使用 Python 标准库
✓ [作者一致性] LICENSE 与 author 一致：不会止步于此
✓ [作者一致性] README 与 author 一致

三、包信息
路径：C:\Users\HUAWEI\WorkBuddy AI\2026-10-19-23-19-50\dist\planweaver-1.0.0.zip
大小：74,730 字节（73.0 KB）
```
