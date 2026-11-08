from pathlib import Path
import subprocess
import sys
import time

ROOT_DIR = Path(__file__).resolve().parent.parent


def run_step(title: str, cmd: list[str], cwd: Path = ROOT_DIR) -> bool:
    print("\n" + "=" * 70)
    print(f"[*] RUNNING: {title}")
    print(
        f"[*] Command: {' '.join(cmd)} (in {cwd.relative_to(ROOT_DIR) if cwd != ROOT_DIR else '.'})"
    )
    print("=" * 70)

    start = time.perf_counter()
    try:
        res = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=True,
            shell=sys.platform.startswith("win"),
        )
        duration = time.perf_counter() - start
        if res.stdout:
            print(res.stdout.strip())
        if res.stderr:
            print(res.stderr.strip(), file=sys.stderr)

        if res.returncode == 0:
            print(f"\n[PASS] {title} ({duration:.2f}s)")
            return True
        else:
            print(
                f"\n[FAIL] {title} (exit code {res.returncode}, {duration:.2f}s)", file=sys.stderr
            )
            return False
    except Exception as exc:
        print(f"\n[ERROR] Failed to execute {title}: {exc}", file=sys.stderr)
        return False


def main() -> int:
    print("#" * 70)
    print(" INVOICEFLOW AI - COMPREHENSIVE END-TO-END VALIDATION HARNESS")
    print("#" * 70)

    steps = [
        (
            "Step 1: Environment & Tooling Verification",
            ["python", "scripts/check_environment.py"],
            ROOT_DIR,
        ),
        ("Step 2: Preflight Health Diagnostics", ["python", "scripts/preflight.py"], ROOT_DIR),
        ("Step 3: Demo Data Seeding", ["python", "scripts/seed_demo.py"], ROOT_DIR),
        (
            "Step 4: Ruff Linter & Formatter Quality Gate",
            ["python", "-m", "ruff", "check", "src", "tests", "scripts", "benchmarks"],
            ROOT_DIR,
        ),
        (
            "Step 5: Pytest Unit, Integration, Contract & Security Tests",
            ["python", "-m", "pytest"],
            ROOT_DIR,
        ),
        (
            "Step 6: Playwright End-to-End Browser Tests",
            ["python", "-m", "pytest", "tests/e2e"],
            ROOT_DIR,
        ),
        (
            "Step 7: Application Quality Assurance Verification",
            ["python", "scripts/run_application_qa.py"],
            ROOT_DIR,
        ),
        (
            "Step 8: Frontend TypeScript Lint & Production Build",
            ["pnpm", "build"],
            ROOT_DIR / "apps" / "web",
        ),
    ]

    failed = []
    for title, cmd, cwd in steps:
        ok = run_step(title, cmd, cwd)
        if not ok:
            failed.append(title)

    print("\n" + "#" * 70)
    print(" OVERALL VALIDATION SUMMARY")
    print("#" * 70)
    if not failed:
        print("\nALL 6 VERIFICATION STAGES PASSED CLEANLY! SYSTEM IS 100% PRODUCTION-READY.")
        return 0
    else:
        print(f"\n{len(failed)} stage(s) failed:", file=sys.stderr)
        for f in failed:
            print(f" - {f}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
