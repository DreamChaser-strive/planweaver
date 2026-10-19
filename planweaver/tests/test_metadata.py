# -*- coding: utf-8 -*-
"""Skill 包元数据与发布合规检查：frontmatter、引用完整性、敏感信息、模板可用性。"""

from __future__ import annotations

import os
import py_compile
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import SKILL_ROOT, parse_frontmatter  # noqa: E402
from validate_plan import Validator  # noqa: E402

SKILL_MD = os.path.join(SKILL_ROOT, "SKILL.md")

# 官方文档未公布 category 枚举；capability 是本地已安装的官方内置 Skill 实际使用的值。
# 平台后台提交时仍需在页面上重新选择分类，见 release/RELEASE-CHECKLIST.md。
VERIFIED_CATEGORIES = {"capability", "writing"}


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def package_files():
    for root, dirs, files in os.walk(SKILL_ROOT):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git"}]
        for name in files:
            yield os.path.join(root, name)


class FrontmatterTests(unittest.TestCase):
    def setUp(self):
        self.text = read(SKILL_MD)
        self.meta = parse_frontmatter(self.text)

    def test_parses(self):
        self.assertGreater(len(self.meta), 5)

    def test_required_fields(self):
        for field in ("description", "description_zh", "description_en", "version", "author"):
            self.assertIn(field, self.meta, f"缺少官方必填字段 {field}")
            self.assertTrue(self.meta[field].strip(), f"{field} 不能为空")

    def test_identity_fields(self):
        self.assertEqual(self.meta.get("name"), "planweaver")
        self.assertEqual(self.meta.get("display_name"), "PlanWeaver 全域智能规划师")
        self.assertIn("PlanWeaver", self.meta.get("display_name_en", ""))

    def test_category_is_verified_value(self):
        category = self.meta.get("category")
        self.assertIn(category, VERIFIED_CATEGORIES,
                      f"category={category!r} 不在已验证的取值内；"
                      f"官方文档未公布枚举，需先在后台确认")

    def test_version_semver(self):
        self.assertRegex(self.meta["version"], r"^\d+\.\d+\.\d+$")

    def test_description_lengths(self):
        self.assertGreaterEqual(len(self.meta["description_zh"]), 20)
        self.assertLessEqual(len(self.meta["description_zh"]), 300)
        self.assertGreaterEqual(len(self.meta["description_en"]), 60)

    def test_description_has_triggers(self):
        description = self.meta["description"]
        for keyword in ("计划", "规划"):
            self.assertIn(keyword, description)
        self.assertGreater(len(description), 80, "描述太短，自动触发会不准")

    def test_no_ascii_colon_in_values(self):
        """官方文档提醒：值里出现半角冒号容易解析失败。"""
        for key, value in self.meta.items():
            self.assertNotIn(": ", value, f"{key} 的值含半角冒号+空格，可能破坏 YAML 解析")

    def test_no_fullwidth_quotes_in_values(self):
        for key, value in self.meta.items():
            self.assertFalse(value.startswith(("“", "”", '"')),
                             f"{key} 的值以引号开头，容易被解析器误判")

    def test_author_placeholder_documented(self):
        author = self.meta["author"]
        if "待填写" not in author:
            self.assertGreater(len(author), 1)
            return
        checklist = os.path.join(os.path.dirname(SKILL_ROOT), "release", "RELEASE-CHECKLIST.md")
        if not os.path.isfile(checklist):
            self.skipTest("发布检查清单不在当前目录结构中")
        self.assertIn("author", read(checklist).lower(),
                      "author 是占位符，必须在发布检查清单中标记为必填项")


class AuthorConsistencyTests(unittest.TestCase):
    """作者信息必须四处一致：SKILL.md / LICENSE / README / 市场文案。"""

    LICENSE_TOKEN = "<AUTHOR_NAME_PLACEHOLDER>"

    def setUp(self):
        self.author = parse_frontmatter(read(SKILL_MD)).get("author", "").strip()
        self.assertTrue(self.author, "author 不能为空")
        self.is_placeholder = "待填写" in self.author

    def _license_holder(self):
        content = read(os.path.join(SKILL_ROOT, "LICENSE"))
        match = re.search(r"Copyright \(c\) \d{4} (.+)", content)
        self.assertIsNotNone(match, "LICENSE 缺少 Copyright 行")
        return match.group(1).strip()

    def test_license_matches(self):
        holder = self._license_holder()
        allowed = {self.author, self.LICENSE_TOKEN}
        self.assertIn(holder, allowed,
                      f"LICENSE 著作权人 {holder!r} 与 author {self.author!r} 不一致")
        if not self.is_placeholder:
            self.assertEqual(holder, self.author, "已填作者时，LICENSE 必须用同一个名字")

    def test_readme_matches(self):
        content = read(os.path.join(SKILL_ROOT, "README.md"))
        self.assertIn(f"- **作者**：{self.author}", content,
                      "README 缺少作者行，或与 SKILL.md 的 author 不一致")

    def test_marketing_matches(self):
        path = os.path.join(os.path.dirname(SKILL_ROOT), "release", "MARKETING.md")
        if not os.path.isfile(path):
            self.skipTest("市场文案不在当前目录结构中")
        content = read(path)
        self.assertIn(f"| 发布者 | {self.author}", content,
                      "市场文案的发布者与 SKILL.md 的 author 不一致")

    def test_only_known_placeholders(self):
        """占位符只能是已知的两种形式，出现第三种就会漏替换。"""
        content = read(os.path.join(SKILL_ROOT, "LICENSE")) + read(
            os.path.join(SKILL_ROOT, "README.md"))
        tokens = re.findall(r"<[A-Z_]*AUTHOR[A-Z_]*>", content)
        for token in tokens:
            self.assertEqual(token, self.LICENSE_TOKEN, f"出现未知占位符 {token}")


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.text = read(SKILL_MD)

    def test_referenced_files_exist(self):
        refs = re.findall(r"@((?:references|templates|scripts)/[\w.\-]+)", self.text)
        self.assertTrue(refs, "SKILL.md 应当引用参考资料")
        for ref in sorted(set(refs)):
            self.assertTrue(os.path.isfile(os.path.join(SKILL_ROOT, ref)),
                            f"引用了不存在的文件：{ref}")

    def test_no_orphan_references(self):
        """references/ 下的文件都应被 SKILL.md 引用，避免上下文浪费。"""
        refs = set(re.findall(r"@references/([\w.\-]+)", self.text))
        directory = os.path.join(SKILL_ROOT, "references")
        for name in os.listdir(directory):
            if name.endswith(".md"):
                self.assertIn(name, refs, f"references/{name} 未被 SKILL.md 引用")

    def test_templates_are_substantive(self):
        directory = os.path.join(SKILL_ROOT, "templates")
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            content = read(path)
            self.assertGreater(len(content), 400, f"{name} 太短，可能只是占位")
            if name.endswith(".md"):
                self.assertIn("|", content, f"{name} 应包含可用的表格结构")

    def test_state_template_validates(self):
        import json
        path = os.path.join(SKILL_ROOT, "templates", "plan-state.json")
        with open(path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
        report = Validator(state).run()
        self.assertTrue(report["ok"], report["findings"])
        self.assertEqual(report["counts"]["warnings"], 0, report["findings"])


class HygieneTests(unittest.TestCase):
    def test_no_todo_or_pseudocode(self):
        pattern = re.compile(r"\b(TODO|FIXME|XXX|PLACEHOLDER)\b|待补充|待实现|伪代码")
        for path in package_files():
            if path.endswith((".py", ".md", ".json")) and "tests" not in path:
                content = read(path)
                for match in pattern.finditer(content):
                    self.fail(f"{os.path.relpath(path, SKILL_ROOT)} 含未完成标记："
                              f"{match.group(0)}")

    def test_no_secrets(self):
        patterns = [
            r"sk-[A-Za-z0-9]{16,}",
            r"BEGIN [A-Z ]*PRIVATE KEY",
            r"(?i)api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9]{8,}",
            r"(?i)password\s*[:=]\s*['\"][^'\"]+",
            r"(?i)secret\s*[:=]\s*['\"][^'\"]+",
        ]
        for path in package_files():
            if path.endswith((".py", ".md", ".json", ".txt")):
                content = read(path)
                for pattern in patterns:
                    self.assertIsNone(re.search(pattern, content),
                                      f"{os.path.relpath(path, SKILL_ROOT)} 疑似包含密钥")

    def test_no_personal_data(self):
        email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
        phone = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
        allow = {"@references/", "@templates/", "@scripts/"}
        for path in package_files():
            if path.endswith((".py", ".md", ".json")):
                content = read(path)
                for hit in email.findall(content):
                    if any(hit.startswith(prefix.strip("@")) for prefix in allow):
                        continue
                    self.fail(f"{os.path.relpath(path, SKILL_ROOT)} 含邮箱：{hit}")
                self.assertIsNone(phone.search(content),
                                  f"{os.path.relpath(path, SKILL_ROOT)} 含手机号样式数字")

    def test_no_build_artifacts(self):
        for path in package_files():
            name = os.path.basename(path)
            self.assertNotIn("__pycache__", path)
            self.assertFalse(name.endswith((".pyc", ".bak", ".tmp")), name)

    def test_scripts_compile(self):
        for name in os.listdir(os.path.join(SKILL_ROOT, "scripts")):
            if name.endswith(".py"):
                with tempfile.TemporaryDirectory() as tmp:
                    py_compile.compile(os.path.join(SKILL_ROOT, "scripts", name),
                                       cfile=os.path.join(tmp, name + "c"),
                                       doraise=True)

    def test_stdlib_only(self):
        """脚本不得引入第三方依赖。"""
        stdlib_ok = {
            "argparse", "datetime", "json", "os", "re", "shutil", "sys",
            "collections", "typing", "__future__", "tempfile", "subprocess",
            "py_compile", "unittest", "copy", "pathlib", "math", "io", "textwrap",
        }
        pattern = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", re.M)
        for name in os.listdir(os.path.join(SKILL_ROOT, "scripts")):
            if not name.endswith(".py"):
                continue
            content = read(os.path.join(SKILL_ROOT, "scripts", name))
            for module in pattern.findall(content):
                root = module.split(".")[0]
                if root in {"validate_plan", "plan_tool"}:
                    continue
                self.assertIn(root, stdlib_ok,
                              f"{name} 引入了非标准库依赖 {module}")


class DocumentTests(unittest.TestCase):
    def test_readme_covers_essentials(self):
        content = read(os.path.join(SKILL_ROOT, "README.md"))
        for keyword in ("安装", "调用", "限制", "plan-state.json", "示例"):
            self.assertIn(keyword, content, f"README 缺少 {keyword} 说明")

    def test_changelog_has_version(self):
        content = read(os.path.join(SKILL_ROOT, "CHANGELOG.md"))
        self.assertIn("1.0.0", content)

    def test_license_is_mit(self):
        content = read(os.path.join(SKILL_ROOT, "LICENSE"))
        self.assertIn("MIT License", content)
        self.assertIn("Permission is hereby granted", content)

    def test_skill_md_within_budget(self):
        content = read(SKILL_MD)
        self.assertLess(len(content), 30000, "SKILL.md 过长，会挤占上下文；把细节移到 references/")

    def test_skill_md_declares_red_lines(self):
        content = read(SKILL_MD)
        for keyword in ("不虚构", "不机械顺延", "不越权"):
            self.assertIn(keyword, content)

    def test_skill_md_covers_all_modes(self):
        content = read(SKILL_MD)
        modes = ("A 全面规划", "B 快速决策", "C 每日安排", "D 进度更新",
                 "E 动态重规划", "F 目标冲突协调", "G 阶段复盘")
        for mode in modes:
            self.assertIn(mode, content, f"缺少模式定义：{mode}")
        self.assertIn("模式路由", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
