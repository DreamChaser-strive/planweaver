# PlanWeaver 发布前检查清单

> 版本：1.0.0　|　检查日期：2026-10-20（发布前复核）
> 结论：**技术项全部通过；有 3 项必须由发布者本人完成（见 §1），完成后才可提交审核。**

---

## 1. 阻断项（必须由你完成，我无法代办）

| # | 项目 | 当前状态 | 怎么处理 |
|---|---|---|---|
| B1 | `SKILL.md` 的 `author` 字段 | ✅ 已写入 `不会止步于此` | 一条命令写入：`python tools/build_release.py --author "你的名字或公司名" --both`（会同时写 SKILL.md / LICENSE / README / MARKETING 四处并自检一致性） |
| B2 | `LICENSE` 的著作权人 | ✅ 已写入 `不会止步于此` | 同上，`--author` 已覆盖（该缺陷在本轮修复：早期版本只处理带扩展名的文件，会漏掉 LICENSE） |
| B3 | 开放平台后台的「分类」「服务类目」「头像」 | ⚠️ 未填写 | 只能在后台页面选择：分类选最接近实际用途的一项；服务类目按后台枚举选；头像需 1 张方图（建议 512×512 PNG） |
| B4 | 开发者实名认证 | ⚠️ 未完成 | 个人认证即可发布技能；企业认证才能发布 Buddy 应用与硬件 |

> 没有 `author` 就不能提交。占位符原样上传会被审核退回。

---

## 2. 元数据检查

| 检查项 | 结果 | 说明 |
|---|---|---|
| `SKILL.md` 使用 YAML frontmatter | ✅ | `---` 开头结尾，字段格式为 `key: value`（冒号后带空格） |
| 必填字段齐全 | ✅ | `description` / `description_zh` / `description_en` / `version` / `author` 均存在 |
| `name` | ✅ | `planweaver` |
| `display_name` | ✅ | `PlanWeaver 全域智能规划师` |
| `display_name_en` | ✅ | `PlanWeaver Universal Planner` |
| `version` | ✅ | `1.0.0`（语义化版本） |
| `category` | ⚠️ 待后台确认 | 使用 `capability`。**官方文档仍未公布枚举**（2026-10-20 复核：`/docs/skill/publish` 返回 404，无发布专页；文档只出现过示例值 `writing`）。该值取自本地已安装的官方内置 Skill（`workbuddy-docx` 下 5 个 Skill 均使用此值）。提交时后台会让你重新选择分类，以页面选项为准 |
| frontmatter 可解析 | ✅ | `tests/test_metadata.py` 用独立解析器验证，且检查值中无半角冒号+空格、无引号开头 |
| 描述含触发词 | ✅ | 含"做计划/规划/排期/延期/重排/复盘/下一步做什么"等 |

---

## 3. 文件与引用完整性

| 检查项 | 结果 |
|---|---|
| `references/` 下 5 个文件均存在 | ✅ |
| `templates/` 下 4 个文件均存在 | ✅ |
| `scripts/` 下 2 个脚本均存在 | ✅ |
| `SKILL.md` 中所有 `@references/...` `@templates/...` 引用均可解析 | ✅（自动化测试覆盖） |
| 无"孤儿参考文档"（未被引用的 references 文件） | ✅ |
| `templates/plan-state.json` 可直接通过校验 | ✅（0 错误 0 警告） |
| 模板非空壳（长度 > 400 字符、含可用表格） | ✅ |

---

## 4. 脚本可用性

| 检查项 | 结果 |
|---|---|
| 仅依赖 Python 标准库 | ✅（自动化测试扫描 import，白名单校验） |
| 无网络请求、无第三方 API | ✅（代码中无 socket/requests/urllib 调用） |
| 两个脚本均可编译 | ✅（`py_compile`） |
| `validate_plan.py` 退出码 0/1/2 正确 | ✅ |
| `plan_tool.py` 全部子命令可执行 | ✅（init/update/replan/add-task/summary/validate/export） |
| 写入前自动备份 | ✅ |
| 原子写入（tmp + replace） | ✅ |
| 保留未知字段 | ✅（测试覆盖） |

---

## 5. 测试结果

执行：`python tests/run_tests.py`

| 套件 | 用例数 | 结果 |
|---|---|---|
| `test_scenarios.py`（12 个必测场景） | 12 | ✅ 全部通过 |
| `test_validator.py`（校验器单元） | 47 | ✅ 全部通过 |
| `test_plan_tool.py`（状态工具 CLI） | 16 | ✅ 全部通过 |
| `test_metadata.py`（包合规 + 作者一致性） | 30 | ✅ 全部通过 |
| **合计** | **105** | **105 通过 / 0 失败 / 0 错误** |

`test_author_placeholder_documented` 会校验本文件确实把 `author` 标为必填；在只复制了 Skill 目录、没有 `release/` 的环境里该项会自动跳过。另新增 4 项作者一致性测试（SKILL.md / LICENSE / README / MARKETING 四处比对）。

---

## 6. 内容合规

| 检查项 | 结果 |
|---|---|
| 无 TODO / FIXME / 待实现 / 伪代码 | ✅（自动化扫描，`author` 占位符为唯一例外且已登记为阻断项） |
| 无密钥、token、密码 | ✅ |
| 无邮箱、手机号等个人信息 | ✅ |
| 无真实用户计划或执行记录 | ✅（所有示例均为虚构，日期与人名不对应真实个体） |
| 无硬编码本地绝对路径 | ✅ |
| 无不必要权限声明（未使用 `allowed-tools`） | ✅ |
| 示例数据标注为虚构 | ✅（`output-examples.md` 首行声明） |

---

## 7. 打包检查

| 检查项 | 结果 |
|---|---|
| ZIP 顶层结构 | `planweaver/SKILL.md`（与官方文档 `{skill-name}/SKILL.md` 一致） |
| 文件数与体积 | 15 个文件 / 74,730 字节（73.0 KB），解压后 189,367 字节 |
| 是否含 tests/ | ❌ 已剔除（官方约定目录只有 references/scripts/templates）；内部归档可加 `--with-tests` |
| 独立审计 | `tools/audit_package.py`：33 通过 / 1 警告 / 0 失败，详见 `PACKAGE-AUDIT.md` |
| 无多余嵌套目录 | ✅ |
| 未包含 `__pycache__` / `.pyc` / `.bak` / `backups/` | ✅（构建脚本按规则剔除） |
| 未包含个人计划状态文件 | ✅ |
| 文件编码统一 UTF-8 | ✅ |
| 构建可复现（固定时间戳） | ✅ |

构建命令：

```bash
python tools/build_release.py --author "你的名字" --both
python tools/audit_package.py --zip dist/planweaver-1.0.0.zip
```

---

## 8. 发布前最后一分钟自问

- [ ] `author` 已换成真实名称，且 SKILL.md / LICENSE / README / MARKETING 四处一致（构建脚本会自检）
- [ ] 在 WorkBuddy 里实际装了一次，说"帮我规划一下"能触发
- [ ] 问它"我落后三天了"时，它**没有**把全部任务整体后移
- [ ] 时间明显不够时，它**说了不行**，并给了取舍
- [ ] 后台分类与服务类目已选，头像已上传
- [ ] 没有在对话里留下真实姓名、公司内部数据

---

## 9. 审核可能被问到的点（提前准备答复）

| 可能的质疑 | 建议答复 |
|---|---|
| 和普通待办/日程工具的区别 | 强调"统一资源账本 + 影响分析 + 冻结不受影响任务"，并给出"落后三天但不需要重排"的案例（`output-examples.md` 3A） |
| `category` 值与后台分类不一致 | 以后台选择为准，YAML 里的值仅作声明 |
| 为什么有两个 Python 脚本 | 确定性校验（容量/依赖/硬截止）与状态读写，避免模型口算；均无网络请求 |
| 数据是否上传 | 不上传。状态文件在用户本地，脚本无网络代码 |
| 是否会替用户做决定 | 不会。多目标冲突只给取舍表，放弃目标必须用户确认 |
