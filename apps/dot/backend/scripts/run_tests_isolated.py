"""Run all test files in isolated processes and aggregate results.

Usage: python scripts/run_tests_isolated.py

Each test_*.py file is run as an independent pytest invocation,
eliminating cross-module state contamination (settings, DB singleton,
FastAPI dependency overrides, etc.).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent.parent / "app" / "tests"

def main() -> None:
    test_files = sorted(TEST_DIR.glob("test_*.py"))
    if not test_files:
        print("No test files found in", TEST_DIR)
        sys.exit(1)

    total = len(test_files)
    passed = 0
    failed = 0
    failures: list[str] = []

    for i, f in enumerate(test_files, 1):
        name = f.stem
        print(f"[{i}/{total}] {name}...", end=" ", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(f), "-q", "--tb=short", "--color=no"],
            capture_output=True,
            text=True,
            cwd=f.parent.parent,  # apps/dot/backend
            timeout=300,
        )
        if result.returncode == 0:
            passed += 1
            print("OK")
        else:
            failed += 1
            failures.append(name)
            print("FAILED")
            # Print last 10 lines of output for context
            lines = [l for l in result.stdout.splitlines() if l.strip()]
            for line in lines[-8:]:
                print(f"    {line}")

    print(f"\n{'='*50}")
    print(f"Total: {total} files | Passed: {passed} | Failed: {failed}")
    if failures:
        print(f"Failures: {', '.join(failures)}")
        sys.exit(1)
    else:
        print("All tests passed in isolation.")
        sys.exit(0)


if __name__ == "__main__":
    main()
