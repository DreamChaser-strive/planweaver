#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PlanWeaver 发布包审计：对 ZIP 或目录做逐项检查，输出清单与结论。

用法:
    python tools/audit_package.py --zip dist/planweaver-1.0.0.zip
    python tools/audit_package.py --zip dist/planweaver-1.0.0.zip --format json
    python tools/audit_package.py --dir planweaver

退出码: 0 全部通过 / 1 存在失败项 / 2 输入不可读

只做只读检查，不修改任何文件。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile

SKILL_NAME = "planweaver"
REQUIRED_FIELDS = ("name", "description", "description_zh", "description_en", "version", "author", "category")

# 官方文档列出的子资源目录；多出来的目录不一定是错，但要报出来让人判断
KNOWN_DIRS = {"references", "scripts", "templates"}
KNOWN_ROOT_FILES = {"SKILL.md", "README.md", "CHANGELOG.md", "LICENSE"}

FORBIDDEN_PARTS = ("__pycache__", ".git", "backups", ".pytest_cache", "node_modules")
FORBIDDEN_SUFFIXES = (".pyc", ".pyo", ".bak", ".tmp", ".log", ".DS_Store")
FORBIDDEN_NAMES = {".DS_Store", "Thumbs.db", ".env"}

TODO_PATTERN = re.compile(r"\b(TODO|FIXME|XXX)\b|待补充|待实现|伪代码")
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9]{8,}"),
    re.compile(r"(?i)password\s*[:=]\s*['\"][^'\"]+"),
)
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
PHONE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

STDLIB_OK = {
    "argparse", "datetime", "json", "os", "re", "shutil", "sys", "collections",
    "typing", "__future__", "tempfile", "subprocess", "py_compile", "unittest",
    "copy", "pathlib", "math", "io", "textwrap", "zlib", "struct", "hashlib", "zipfile",
    "time", "glob", "random", "statistics", "itertools", "functools", "csv", "base64",
}


class Audit:
    def __init__(self):
        self.items = []
        self.files = []

    def add(self, level, item, detail, expected=""):
        self.items.append({"level": level, "item": item, "detail": detail, "expected": expected})

    def ok(self, item, detail, expected=""):
        self.add("pass", item, detail, expected)

    def warn(self, item, detail, expected=""):
        self.add("warn", item, detail, expected)

    def fail(self, item, detail, expected=""):
        self.add("fail", item, detail, expected)

    def counts(self):
        return {
            "pass": sum(1 for i in self.items if i["level"] == "pass"),
            "warn": sum(1 for i in self.items if i["level"] == "warn"),
            "fail": sum(1 for i in self.items if i["level"] == "fail"),
        }


def parse_frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return None
    data = {}
    key = None
    buffer = []
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        if raw[0] in " \t":
            buffer.append(raw.strip())
            continue
        if ":" not in raw:
            continue
        if key:
            data[key] = " ".join(buffer).strip()
            buffer = []
        name, _, value = raw.partition(":")
        key = name.strip()
        value = value.strip()
        if value in (">", "|", ">-", "|-", ""):
            buffer = []
            if value == "":
                key = key  # 空值占位，等缩进块
            continue
        data[key] = value
        key = None
    if key:
        data[key] = " ".join(buffer).strip()
    return data


def is_text_entry(name):
    """需要读内容的文件：代码/文档/配置，外加 LICENSE 这类无扩展名文件。"""
    base = os.path.basename(name)
    if base in {"LICENSE", "NOTICE", "AUTHORS"}:
        return True
    return name.lower().endswith((".md", ".py", ".json", ".txt", ".yml", ".yaml"))


def load_zip(path):
    with zipfile.ZipFile(path) as archive:
        entries = [(info.filename, info.file_size) for info in archive.infolist()
                   if not info.is_dir()]
        contents = {name: archive.read(name).decode("utf-8", errors="replace")
                    for name, _ in entries if is_text_entry(name)}
    return entries, contents


def load_dir(path):
    entries, contents = [], {}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in FORBIDDEN_PARTS]
        for name in files:
            full = os.path.join(root, name)
            relative = os.path.relpath(full, path).replace(os.sep, "/")
            size = os.path.getsize(full)
            entries.append((relative, size))
            if is_text_entry(name):
                with open(full, "r", encoding="utf-8", errors="replace") as handle:
                    contents[relative] = handle.read()
    return sorted(entries), contents


def detect_layout(entries, audit):
    """返回 (prefix, flat)。prefix 是包内 Skill 目录前缀（含尾部斜杠），扁平包为空串。"""
    names = [name for name, _ in entries]
    if "SKILL.md" in names:
        audit.ok("目录结构", "扁平结构：SKILL.md 位于包根")
        return "", True

    tops = sorted({name.split("/")[0] for name in names})
    if len(tops) == 1 and tops[0] == SKILL_NAME and f"{SKILL_NAME}/SKILL.md" in names:
        audit.ok("目录结构", f"单顶层目录 {SKILL_NAME}/，SKILL.md 在目录根（与官方结构图一致）")
        return f"{SKILL_NAME}/", False

    audit.fail("目录结构", f"顶层条目为 {tops}，既不是单一 {SKILL_NAME}/ 目录，也不是扁平结构",
               f"ZIP 根下只应有一个 {SKILL_NAME}/ 目录，且其中含 SKILL.md")
    return "", False


def audit_package(entries, contents, audit):
    entries = sorted(entries)
    names = [name for name, _ in entries]
    audit.files = [{"path": name, "bytes": size} for name, size in entries]

    total = sum(size for _, size in entries)
    audit.ok("文件清单", f"共 {len(entries)} 个文件，解压后合计 {total:,} 字节（{total / 1024:.1f} KB）")

    prefix, flat = detect_layout(entries, audit)

    def has(relative):
        return f"{prefix}{relative}" in names

    def get(relative):
        return contents.get(f"{prefix}{relative}", "")

    # 1. 必需文件
    text = get("SKILL.md")
    missing = [] if text else ["SKILL.md"]
    if missing:
        audit.fail("必需文件", "缺少 SKILL.md", "SKILL.md 是唯一的必需文件")
    else:
        audit.ok("必需文件", f"SKILL.md 存在（{len(text):,} 字符）")
    for optional in ("README.md", "CHANGELOG.md", "LICENSE"):
        if has(optional):
            audit.ok("必需文件", f"{optional} 存在（{len(get(optional)):,} 字符）")
        else:
            audit.warn("必需文件", f"缺少 {optional}（官方非必需，但发布建议齐全）")

    # 2. frontmatter
    meta = parse_frontmatter(text) if text else None
    if meta is None:
        audit.fail("frontmatter", "SKILL.md 无法解析出 frontmatter", "需以 --- 开头并以 --- 结束")
        meta = {}
    else:
        audit.ok("frontmatter", f"可解析，共 {len(meta)} 个字段")
        for field in REQUIRED_FIELDS:
            if meta.get(field):
                audit.ok("frontmatter", f"{field} = {meta[field][:40]}")
            else:
                audit.fail("frontmatter", f"缺少必填字段 {field}", "官方要求该字段必填")
        if meta.get("name") and meta["name"] != SKILL_NAME:
            audit.fail("frontmatter", f"name={meta['name']} 与包名 {SKILL_NAME} 不一致")
        version = meta.get("version", "")
        if version and not re.match(r"^\d+\.\d+\.\d+$", version):
            audit.fail("frontmatter", f"version={version} 不是语义化版本")
        category = meta.get("category", "")
        if category:
            audit.warn("frontmatter", f"category={category}（官方文档未公布枚举，需在后台确认）",
                       "后台分类选择以页面选项为准")
        for key, value in meta.items():
            if ": " in value:
                audit.warn("frontmatter", f"{key} 的值含半角冒号+空格，可能影响解析")

    # 3. 引用完整性
    refs = sorted(set(re.findall(r"@((?:references|templates|scripts)/[\w.\-]+)", text)))
    if not refs:
        audit.warn("引用完整性", "SKILL.md 未通过 @ 引用任何子资源")
    for ref in refs:
        if has(ref):
            audit.ok("引用完整性", f"@{ref} 可解析")
        else:
            audit.fail("引用完整性", f"@{ref} 在包内不存在", "补上文件或修正引用路径")

    # 4. 子目录内容
    for directory in sorted(KNOWN_DIRS):
        files = [n for n in names if n.startswith(f"{prefix}{directory}/")]
        if files:
            audit.ok(f"{directory}/", f"{len(files)} 个文件：" +
                     ", ".join(os.path.basename(f) for f in sorted(files)))
        else:
            audit.warn(f"{directory}/", "目录为空或缺失（可选，但本 Skill 声明了该目录的用途）")

    # 5. 多余内容
    for name in names:
        relative = name[len(prefix):] if prefix and name.startswith(prefix) else name
        parts = relative.split("/")
        if any(part in FORBIDDEN_PARTS for part in parts):
            audit.fail("多余内容", f"{name} 属于缓存/备份目录")
        if name.endswith(FORBIDDEN_SUFFIXES) or os.path.basename(name) in FORBIDDEN_NAMES:
            audit.fail("多余内容", f"{name} 是临时文件或系统文件")
    extra_dirs = {relative.split("/")[0] for name in names
                  for relative in [name[len(prefix):] if prefix and name.startswith(prefix) else name]
                  if "/" in relative}
    unexpected = extra_dirs - KNOWN_DIRS - {"tests"}
    if unexpected:
        audit.warn("多余内容", f"存在非官方约定的顶层目录：{sorted(unexpected)}",
                   "官方只列出 references/scripts/templates；多出的目录需确认平台是否接受")
    if "tests" in extra_dirs:
        audit.warn("多余内容", "包含 tests/ 目录（开发自测用，平台未列入约定目录）",
                   "若平台解析失败，可用 --without-tests 构建精简包")

    # 6. 内容合规
    todo_hits, secret_hits, email_hits, phone_hits = [], [], [], []
    for name, content in contents.items():
        is_test = "/tests/" in name or name.startswith(f"{prefix}tests/")
        patterns = ((EMAIL_PATTERN, email_hits), (PHONE_PATTERN, phone_hits))
        if not is_test:   # 测试文件里本身就写着 TODO/FIXME 这些字面量
            patterns = ((TODO_PATTERN, todo_hits),) + patterns
        for pattern, bucket in patterns:
            for match in pattern.finditer(content):
                bucket.append(f"{name}: {match.group(0)[:30]}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                secret_hits.append(name)
    audit.fail("内容合规", f"发现未完成标记：{todo_hits[:5]}") if todo_hits else \
        audit.ok("内容合规", "无 TODO/FIXME/待补充")
    audit.fail("内容合规", f"疑似密钥：{sorted(set(secret_hits))}") if secret_hits else \
        audit.ok("内容合规", "无密钥/token/密码样式字符串")
    audit.fail("内容合规", f"疑似邮箱：{email_hits[:3]}") if email_hits else \
        audit.ok("内容合规", "无邮箱地址")
    audit.fail("内容合规", f"疑似手机号：{phone_hits[:3]}") if phone_hits else \
        audit.ok("内容合规", "无手机号样式数字")

    # 7. 依赖
    bad_imports = []
    local_modules = {os.path.splitext(os.path.basename(n))[0]
                     for n in names if n.endswith(".py")}
    pattern = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", re.M)
    for name, content in contents.items():
        if not name.endswith(".py"):
            continue
        for module in pattern.findall(content):
            root = module.split(".")[0]
            if root in local_modules or root in STDLIB_OK:
                continue
            bad_imports.append(f"{name} → {module}")
    bad_imports = sorted(set(bad_imports))
    audit.fail("依赖", f"非标准库依赖：{bad_imports}") if bad_imports else \
        audit.ok("依赖", "所有脚本仅使用 Python 标准库")

    # 8. 作者一致性
    author = (meta.get("author") or "").strip()
    if author:
        license_text = get("LICENSE")
        readme_text = get("README.md")
        holder = re.search(r"Copyright \(c\) \d{4} (.+)", license_text)
        holder = holder.group(1).strip() if holder else ""
        if holder and holder != author and "AUTHOR_NAME_PLACEHOLDER" not in holder:
            audit.fail("作者一致性", f"LICENSE 著作权人 {holder!r} ≠ author {author!r}")
        elif "AUTHOR_NAME_PLACEHOLDER" in holder:
            audit.warn("作者一致性", "LICENSE 仍是占位符（构建时未传 --author）")
        else:
            audit.ok("作者一致性", f"LICENSE 与 author 一致：{author}")
        if readme_text and f"- **作者**：{author}" not in readme_text:
            audit.fail("作者一致性", "README 的作者行与 author 不一致")
        elif readme_text:
            audit.ok("作者一致性", "README 与 author 一致")
        if "待填写" in author:
            audit.fail("作者一致性", f"author 仍是占位符：{author}",
                       "运行 python tools/build_release.py --author \"你的名字\" 重新构建")

    return meta


def render(audit, meta, entries):
    lines = []
    counts = audit.counts()
    verdict = "通过" if counts["fail"] == 0 else "未通过"
    lines.append(f"PlanWeaver 发布包审计：{verdict}")
    lines.append(f"检查项 {len(audit.items)} 个 | 通过 {counts['pass']} | 警告 {counts['warn']} | 失败 {counts['fail']}")
    lines.append("")

    lines.append("一、文件清单")
    lines.append(f"{'字节':>8}  路径")
    for name, size in sorted(entries):
        lines.append(f"{size:>8}  {name}")
    lines.append(f"{sum(s for _, s in entries):>8}  合计 {len(entries)} 个文件")
    lines.append("")

    lines.append("二、逐项检查")
    mark = {"pass": "✓", "warn": "!", "fail": "✗"}
    for item in audit.items:
        lines.append(f"{mark[item['level']]} [{item['item']}] {item['detail']}")
        if item["level"] != "pass" and item["expected"]:
            lines.append(f"    → {item['expected']}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="PlanWeaver 发布包审计（只读）")
    parser.add_argument("--zip", help="待审计的 ZIP")
    parser.add_argument("--dir", help="待审计的目录")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    if not args.zip and not args.dir:
        parser.error("需要 --zip 或 --dir")

    audit = Audit()
    try:
        if args.zip:
            if not os.path.isfile(args.zip):
                print(f"错误：ZIP 不存在（{args.zip}）", file=sys.stderr)
                return 2
            entries, contents = load_zip(args.zip)
            source = os.path.abspath(args.zip)
            size_bytes = os.path.getsize(args.zip)
        else:
            if not os.path.isdir(args.dir):
                print(f"错误：目录不存在（{args.dir}）", file=sys.stderr)
                return 2
            entries, contents = load_dir(args.dir)
            source = os.path.abspath(args.dir)
            size_bytes = 0
    except (zipfile.BadZipFile, OSError) as exc:
        print(f"错误：无法读取（{exc}）", file=sys.stderr)
        return 2

    meta = audit_package(entries, contents, audit)
    counts = audit.counts()

    if args.format == "json":
        print(json.dumps({
            "ok": counts["fail"] == 0,
            "source": source,
            "zip_bytes": size_bytes,
            "counts": counts,
            "frontmatter": meta,
            "files": audit.files,
            "checks": audit.items,
        }, ensure_ascii=False, indent=2))
    else:
        print(render(audit, meta, entries))
        if size_bytes:
            print("")
            print(f"三、包信息\n路径：{source}\n大小：{size_bytes:,} 字节（{size_bytes / 1024:.1f} KB）")
    return 0 if counts["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
