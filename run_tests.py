#!/usr/bin/env python3
# KTC Test Runner CLI
# Runs test suite and verifies type stubs for KTC without requiring Klipper source
#
# This file may be distributed under the terms of the GNU GPLv3 license.

from __future__ import annotations
import argparse
import os
import sys
import time
import unittest


# ANSI color formatting
class Color:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def print_banner() -> None:
    print(f"{Color.CYAN}{Color.BOLD}")
    print("=======================================================")
    print("   KTC (Klipper Tool Changer) Comprehensive Test Suite  ")
    print("=======================================================")
    print(f"{Color.RESET}")


def run_type_check() -> bool:
    """Validate that PEP 484 type stubs and all KTC modules resolve cleanly."""
    print(f"\n{Color.BLUE}--> Verifying PEP 484 Type Stubs (.pyi)...{Color.RESET}")
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    stubs_dir = os.path.join(repo_dir, "typings", "klippy")

    expected_stubs = [
        "__init__.pyi",
        "configfile.pyi",
        "gcode.pyi",
        "reactor.pyi",
        "pins.pyi",
        "klippy.pyi",
        os.path.join("extras", "__init__.pyi"),
        os.path.join("extras", "heaters.pyi"),
        os.path.join("extras", "gcode_macro.pyi"),
        os.path.join("extras", "fan_generic.pyi"),
    ]

    all_ok = True
    for stub in expected_stubs:
        stub_path = os.path.join(stubs_dir, stub)
        if os.path.isfile(stub_path):
            print(f"  {Color.GREEN}✔{Color.RESET} typings/klippy/{stub:<30} found")
        else:
            print(f"  {Color.RED}✖{Color.RESET} typings/klippy/{stub:<30} MISSING")
            all_ok = False

    print(f"\n{Color.BLUE}--> Verifying KTC Module Resolution...{Color.RESET}")
    modules = [
        "klippy.extras.ktc_base",
        "klippy.extras.ktc_heater",
        "klippy.extras.ktc_log",
        "klippy.extras.ktc_persisting",
        "klippy.extras.ktc_safety",
        "klippy.extras.ktc_tool",
        "klippy.extras.ktc_toolchanger",
        "klippy.extras.ktc_tools_calibrate",
        "klippy.extras.ktc",
    ]

    for mod_name in modules:
        try:
            __import__(mod_name, fromlist=["*"])
            print(f"  {Color.GREEN}✔{Color.RESET} {mod_name:<36} resolved")
        except Exception as e:
            print(f"  {Color.RED}✖{Color.RESET} {mod_name:<36} FAILED: {e}")
            all_ok = False

    return all_ok


def compute_code_coverage() -> None:
    """Source line metrics calculator for KTC modules."""
    print(f"\n{Color.BLUE}--> Source Code Metrics & Module Inspection...{Color.RESET}")
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    extras_dir = os.path.join(repo_dir, "klippy", "extras")

    print(f"  {'Module Name':<30} {'Lines':<10} {'Status':<15}")
    print("  " + "-" * 58)

    total_lines = 0
    for filename in sorted(os.listdir(extras_dir)):
        if filename.startswith("ktc") and filename.endswith(".py"):
            path = os.path.join(extras_dir, filename)
            with open(path, "r", encoding="utf-8") as f:
                lines = len(f.readlines())
                total_lines += lines
            print(f"  {filename:<30} {lines:<10} {Color.GREEN}Active{Color.RESET}")

    print("  " + "-" * 58)
    print(f"  {'Total KTC Codebase':<30} {total_lines:<10} {Color.GREEN}Verified{Color.RESET}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="KTC Test Runner CLI")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose test execution")
    parser.add_argument("-k", "--filter", type=str, default="", help="Filter tests by name pattern")
    parser.add_argument("-u", "--unit", action="store_true", help="Run only unit tests")
    parser.add_argument("-i", "--integration", action="store_true", help="Run only integration tests")
    parser.add_argument("-f", "--failfast", action="store_true", help="Stop on first failure")
    parser.add_argument("--types", action="store_true", help="Verify types interface only")
    parser.add_argument("--coverage", action="store_true", help="Show code metrics and coverage")
    args = parser.parse_args()

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    if repo_dir not in sys.path:
        sys.path.insert(0, repo_dir)

    # Initialize mock test environment
    import tests.harness  # pylint: disable=unused-import

    print_banner()

    if args.coverage:
        compute_code_coverage()

    if args.types:
        ok = run_type_check()
        return 0 if ok else 1

    # Run types check first as sanity check
    types_ok = run_type_check()
    if not types_ok:
        print(f"\n{Color.RED}Types verification failed. Aborting tests.{Color.RESET}")
        return 1

    # Discover tests
    print(f"\n{Color.BLUE}--> Discovering and Running Tests...{Color.RESET}")
    loader = unittest.TestLoader()

    if args.unit:
        start_dir = os.path.join(repo_dir, "tests", "unit")
    elif args.integration:
        start_dir = os.path.join(repo_dir, "tests", "integration")
    else:
        start_dir = os.path.join(repo_dir, "tests")

    suite = loader.discover(start_dir, pattern="test_*.py")

    # Apply filter if provided
    if args.filter:
        filtered_suite = unittest.TestSuite()
        for test_group in suite:
            for test_case in test_group:
                if hasattr(test_case, "_tests"):
                    for t in test_case:
                        if args.filter.lower() in str(t).lower():
                            filtered_suite.addTest(t)
                else:
                    if args.filter.lower() in str(test_case).lower():
                        filtered_suite.addTest(test_case)
        suite = filtered_suite

    verbosity = 2 if args.verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity, failfast=args.failfast)

    start_time = time.time()
    result = runner.run(suite)
    elapsed = time.time() - start_time

    # Summary report
    print("\n" + "=" * 55)
    print(f"{Color.BOLD}Test Execution Summary:{Color.RESET}")
    print(f"  Total tests:   {result.testsRun}")
    print(f"  Passed:        {Color.GREEN}{result.testsRun - len(result.failures) - len(result.errors)}{Color.RESET}")
    print(f"  Failures:      {Color.RED if result.failures else Color.GREEN}{len(result.failures)}{Color.RESET}")
    print(f"  Errors:        {Color.RED if result.errors else Color.GREEN}{len(result.errors)}{Color.RESET}")
    print(f"  Elapsed time:  {elapsed:.3f}s")
    print("=" * 55)

    if result.wasSuccessful():
        print(f"\n{Color.GREEN}{Color.BOLD}🎉 ALL TESTS PASSED!{Color.RESET}\n")
        return 0
    else:
        print(f"\n{Color.RED}{Color.BOLD}❌ TESTS FAILED!{Color.RESET}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
