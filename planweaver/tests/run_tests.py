# -*- coding: utf-8 -*-
"""测试入口：运行全部单元测试与场景测试，输出汇总。

用法：
    python tests/run_tests.py
    python tests/run_tests.py -v          # 逐条显示
    python tests/run_tests.py test_scenarios   # 只跑某个模块
"""

from __future__ import annotations

import os
import sys
import time
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    verbosity = 2 if "-v" in argv else 1
    argv = [item for item in argv if item != "-v"]

    loader = unittest.TestLoader()
    if argv:
        suite = unittest.TestSuite()
        for name in argv:
            module = name[:-3] if name.endswith(".py") else name
            suite.addTests(loader.loadTestsFromName(module))
    else:
        suite = loader.discover(start_dir=TESTS_DIR, pattern="test_*.py", top_level_dir=TESTS_DIR)

    print("=" * 68)
    print("PlanWeaver 测试套件")
    print("=" * 68)
    started = time.time()
    runner = unittest.TextTestRunner(verbosity=verbosity, buffer=False)
    result = runner.run(suite)
    elapsed = time.time() - started

    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failures - errors - skipped

    print("-" * 68)
    print(f"合计 {total} 项 | 通过 {passed} | 失败 {failures} | 错误 {errors} | 跳过 {skipped} "
          f"| 用时 {elapsed:.1f}s")
    if failures or errors:
        print("结果：未通过")
        return 1
    print("结果：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
