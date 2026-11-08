import os
import shutil
import subprocess
import sys


def run_cmd(cmd: list[str]) -> tuple[int, str]:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=sys.platform.startswith("win"))
        return res.returncode, (res.stdout + res.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def main() -> int:
    print("=" * 60)
    print(" InvoiceFlow AI - Development Environment Diagnostics")
    print("=" * 60)
    
    # 1. Python version
    py_ver = sys.version.split()[0]
    major, minor = sys.version_info[:2]
    py_ok = (major == 3 and minor >= 11)
    print(f"[*] Python: {py_ver} -> {'[OK]' if py_ok else '[FAIL: Needs >= 3.11]'}")

    # 2. Node.js
    node_path = shutil.which("node")
    if node_path:
        _, node_ver = run_cmd(["node", "--version"])
        print(f"[*] Node.js: {node_ver} -> [OK]")
    else:
        print("[*] Node.js: Not found -> [FAIL]")

    # 3. pnpm
    pnpm_path = shutil.which("pnpm")
    if pnpm_path:
        _, pnpm_ver = run_cmd(["pnpm", "--version"])
        print(f"[*] pnpm: {pnpm_ver} -> [OK]")
    else:
        print("[*] pnpm: Not found -> [FAIL]")

    # 4. Docker
    docker_path = shutil.which("docker")
    if docker_path:
        code, docker_ver = run_cmd(["docker", "--version"])
        if code == 0:
            print(f"[*] Docker: {docker_ver} -> [OK]")
        else:
            print(f"[*] Docker: installed but daemon might not be running -> [WARN]")
    else:
        print("[*] Docker: Not installed -> [WARN]")

    # 5. Env file check
    env_exists = os.path.exists(".env")
    print(f"[*] Environment config (.env): {'[OK]' if env_exists else '[WARN: .env missing, using defaults]'}")

    print("\nEnvironment verification completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
