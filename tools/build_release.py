#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 PlanWeaver 发布包。

做四件事：
1. 校验 SKILL.md frontmatter 的必填字段与占位符；
2. 运行全部测试（可用 --skip-tests 跳过，但发布前不应跳过）；
3. 复制 Skill 目录到临时暂存区，剔除缓存/备份/临时文件；
4. 生成 ZIP（默认带 `planweaver/` 顶层目录，--flat 则把 SKILL.md 放在包根）。

用法：
    python tools/build_release.py --author "你的名字"
    python tools/build_release.py --author "你的名字" --flat
    python tools/build_release.py --author "你的名字" --skip-tests
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(PROJECT_ROOT, "planweaver")
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")

SKILL_NAME = "planweaver"
REQUIRED_FIELDS = ("description", "description_zh", "description_en", "version", "author")
EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache", "backups", "dist", "node_modules"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo", ".bak", ".tmp", ".log", ".DS_Store")
EXCLUDE_FILES = {".DS_Store", "Thumbs.db"}

AUTHOR_PLACEHOLDER = "待填写（发布者名称）"
LICENSE_PLACEHOLDER = "<AUTHOR_NAME_PLACEHOLDER>"

# 作者信息在四处出现，构建时统一写入，避免"改了 SKILL.md 忘了 README"
STAMP_PATTERNS = (
    re.compile(r"(?m)^author:\s*.*$"),
    re.compile(r"(?m)^- \*\*作者\*\*：.*$"),
    re.compile(r"(?m)^\| 发布者 \|.*$"),
    re.compile(r"(?m)^Copyright \(c\) \d{4} .*$"),
)

# 固定时间戳，让重复构建的 ZIP 内容可复现
FIXED_DATE = (2026, 10, 19, 0, 0, 0)


def stamp_author(text, author, year="2026"):
    """把作者写进 SKILL.md / LICENSE / README / 市场文案的既有位置。

    用正则替换"整行"而不是替换占位符字符串，这样即使上一版已经填过名字，
    重新构建也能正确改名（不会出现两处名字不一致）。
    """
    text = STAMP_PATTERNS[0].sub(f"author: {author}", text)
    text = STAMP_PATTERNS[1].sub(f"- **作者**：{author}", text)
    text = STAMP_PATTERNS[2].sub(f"| 发布者 | {author} |", text)
    text = STAMP_PATTERNS[3].sub(f"Copyright (c) {year} {author}", text)
    text = text.replace(AUTHOR_PLACEHOLDER, author)
    text = text.replace(LICENSE_PLACEHOLDER, author)
    return text


def check_author_consistency(root, author):
    """构建后自检：SKILL.md / LICENSE / README 的作者必须是同一个。"""
    checks = {
        "SKILL.md": r"(?m)^author:\s*(.+)$",
        "LICENSE": r"(?m)^Copyright \(c\) \d{4} (.+)$",
        "README.md": r"(?m)^- \*\*作者\*\*：(.+)$",
    }
    found = {}
    for name, pattern in checks.items():
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        match = re.search(pattern, read(path))
        found[name] = match.group(1).strip() if match else None

    problems = []
    for name, value in found.items():
        if not value:
            problems.append(f"{name} 中找不到作者信息")
        elif value != author:
            problems.append(f"{name} 的作者是 {value!r}，与 {author!r} 不一致")
    if problems:
        for problem in problems:
            print(f"✗ {problem}", file=sys.stderr)
        sys.exit(1)
    print(f"→ 作者一致性：{', '.join(found)} 均为 {author}")


def update_source(author):
    """把作者写回源码文件，避免"包里是新名字、仓库里还是占位符"的错位。"""
    targets = ("SKILL.md", "LICENSE", "README.md")
    changed = []
    for name in targets:
        path = os.path.join(SKILL_DIR, name)
        if not os.path.isfile(path):
            continue
        original = read(path)
        updated = stamp_author(original, author)
        if updated != original:
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(updated)
            changed.append(name)
    if changed:
        print(f"→ 已写回源码：{', '.join(changed)}")


def sync_marketing(author):
    """同步更新 release/MARKETING.md 的发布者字段（该文件不在包内）。"""
    path = os.path.join(PROJECT_ROOT, "release", "MARKETING.md")
    if not os.path.isfile(path):
        return
    original = read(path)
    updated = STAMP_PATTERNS[2].sub(f"| 发布者 | {author} |", original)
    if updated != original:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(updated)
        print("→ 已同步 release/MARKETING.md 的发布者字段")


def fail(message):
    print(f"✗ {message}", file=sys.stderr)
    sys.exit(1)


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def parse_frontmatter(text):
    """解析 SKILL.md 的 frontmatter（仅支持本项目用到的 `key: value` 子集）。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        fail("SKILL.md 开头缺少 --- 分隔符")
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        fail("SKILL.md frontmatter 没有结束的 ---")
    data = {}
    for raw in lines[1:end]:
        if not raw.strip() or raw[0] in " \t" or ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        data[key.strip()] = value.strip()
    return data


def check_metadata(meta):
    problems = []
    for field in REQUIRED_FIELDS:
        if not meta.get(field, "").strip():
            problems.append(f"缺少必填字段或值为空：{field}")
    if meta.get("name") != SKILL_NAME:
        problems.append(f"name 应为 {SKILL_NAME}，实际为 {meta.get('name')!r}")
    if not re.match(r"^\d+\.\d+\.\d+$", meta.get("version", "")):
        problems.append(f"version 不是语义化版本：{meta.get('version')!r}")
    if not meta.get("category"):
        problems.append("缺少 category（平台要求）")
    if problems:
        for problem in problems:
            print(f"✗ {problem}", file=sys.stderr)
        sys.exit(1)


def run_tests():
    runner = os.path.join(SKILL_DIR, "tests", "run_tests.py")
    if not os.path.isfile(runner):
        fail(f"测试入口不存在：{runner}")
    print("→ 运行测试…")
    result = subprocess.run([sys.executable, runner], cwd=SKILL_DIR)
    if result.returncode != 0:
        fail("测试未通过，已中止打包。修复后重试，或确认后使用 --skip-tests")
    print("→ 测试通过")


def stage(author, include_tests=False):
    """复制 Skill 目录到暂存区，替换作者占位符。

    默认剔除 tests/：官方结构只约定 references/scripts/templates，
    多出的顶层目录会增加平台解析失败的风险。内部归档时用 --with-tests 保留。
    """
    tmp_root = tempfile.mkdtemp(prefix="planweaver-build-")
    target = os.path.join(tmp_root, SKILL_NAME)
    os.makedirs(target)

    copied = []
    for root, dirs, files in os.walk(SKILL_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS
                   and (include_tests or d != "tests")]
        for name in files:
            if name in EXCLUDE_FILES or name.endswith(EXCLUDE_SUFFIXES):
                continue
            source = os.path.join(root, name)
            relative = os.path.relpath(source, SKILL_DIR)
            destination = os.path.join(target, relative)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            if author and (name.endswith((".md", ".txt", ".json"))
                           or name in {"LICENSE", "NOTICE", "AUTHORS"}):
                content = stamp_author(read(source), author)
                with open(destination, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(content)
            else:
                shutil.copy2(source, destination)
            copied.append(relative.replace(os.sep, "/"))

    return tmp_root, target, sorted(copied)


def make_zip(target, files, version, flat=False):
    os.makedirs(DIST_DIR, exist_ok=True)
    name = f"{SKILL_NAME}-{version}{'-flat' if flat else ''}.zip"
    path = os.path.join(DIST_DIR, name)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        # SKILL.md 放在包内第一个，便于解析器优先读到
        ordered = sorted(files, key=lambda item: (item != "SKILL.md", item))
        for relative in ordered:
            source = os.path.join(target, relative)
            arcname = relative if flat else f"{SKILL_NAME}/{relative}"
            info = zipfile.ZipInfo(arcname, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(source, "rb") as handle:
                archive.writestr(info, handle.read())
    return path


def digest(path):
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description="构建 PlanWeaver 发布 ZIP")
    parser.add_argument("--author", help="发布者名称（写入 SKILL.md / LICENSE / README，并同步市场文案）")
    parser.add_argument("--version", help="覆盖版本号（默认读 SKILL.md）")
    parser.add_argument("--flat", action="store_true",
                        help="生成扁平包（SKILL.md 在 ZIP 根，不带 planweaver/ 目录）")
    parser.add_argument("--skip-tests", action="store_true", help="跳过测试（不推荐）")
    parser.add_argument("--both", action="store_true", help="同时生成带目录与扁平两种包")
    parser.add_argument("--no-sync-marketing", action="store_true",
                        help="不自动更新 release/MARKETING.md 的发布者字段")
    parser.add_argument("--update-source", action="store_true",
                        help="同时把作者写回 planweaver/ 源码（不只是打包副本）")
    parser.add_argument("--with-tests", action="store_true",
                        help="把 tests/ 一并打包（内部归档用；提交平台建议不带）")
    args = parser.parse_args(argv)

    print("→ 检查 SKILL.md…")
    skill_md = os.path.join(SKILL_DIR, "SKILL.md")
    if not os.path.isfile(skill_md):
        fail("找不到 planweaver/SKILL.md")
    meta = parse_frontmatter(read(skill_md))
    check_metadata(meta)
    version = args.version or meta["version"]

    if not args.skip_tests:
        run_tests()
    else:
        print("! 已跳过测试（发布前请勿跳过）")

    author = args.author
    if author:
        print(f"→ 写入发布者：{author}")
    elif AUTHOR_PLACEHOLDER in meta.get("author", ""):
        print("! author 仍是占位符。打包内容将保留占位符，提交审核前必须替换。")
        print("  替换命令：python tools/build_release.py --author \"你的名字\"")
    if author and args.update_source:
        update_source(author)
    if author and not args.no_sync_marketing:
        sync_marketing(author)

    print("→ 暂存文件…")
    tmp_root, target, files = stage(author, include_tests=args.with_tests)
    if not args.with_tests:
        print("→ 已剔除 tests/（官方约定目录只有 references/scripts/templates）")
    try:
        if author:
            check_author_consistency(target, author)

        targets = [False]
        if args.both:
            targets = [False, True]
        elif args.flat:
            targets = [True]

        for flat in targets:
            path = make_zip(target, files, version, flat=flat)
            size = os.path.getsize(path) / 1024
            print(f"\n✓ 已生成：{path}")
            print(f"  大小：{size:.1f} KB | 文件数：{len(files)}")
            print(f"  SHA256：{digest(path)}")
            print(f"  顶层结构：{'扁平（SKILL.md 在根）' if flat else f'{SKILL_NAME}/SKILL.md'}")
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    print("\n包内容：")
    for relative in files:
        print(f"  {relative}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
