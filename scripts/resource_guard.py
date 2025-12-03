#!/usr/bin/env python3
"""Resource guard for limiting memory usage during tests.

This script monitors memory usage and kills the process if it exceeds the limit.
Use as a wrapper: python scripts/resource_guard.py --max-gb 8 -- pytest ...
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time


def get_process_memory_gb(pid: int) -> float:
    """Get memory usage of a process in GB."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    # VmRSS is in KB
                    kb = int(line.split()[1])
                    return kb / (1024 * 1024)
    except (FileNotFoundError, PermissionError, ValueError):
        pass
    return 0.0


def monitor_process(
    proc: subprocess.Popen,
    max_memory_gb: float,
    check_interval: float = 1.0,
) -> None:
    """Monitor process memory and kill if exceeds limit."""
    pid = proc.pid
    print(f"[RESOURCE GUARD] Monitoring PID {pid}, limit: {max_memory_gb} GB")

    while proc.poll() is None:
        mem_gb = get_process_memory_gb(pid)

        # Also check child processes
        try:
            children_pids = []
            with open(f"/proc/{pid}/task/{pid}/children") as f:
                children_pids = [int(c) for c in f.read().split()]
            for child_pid in children_pids:
                mem_gb += get_process_memory_gb(child_pid)
        except (FileNotFoundError, PermissionError, ValueError):
            pass

        if mem_gb > max_memory_gb:
            print(
                f"[RESOURCE GUARD] KILLING: Memory {mem_gb:.2f} GB exceeds "
                f"limit {max_memory_gb} GB"
            )
            proc.kill()
            # Also kill process group
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            return

        if mem_gb > max_memory_gb * 0.8:
            print(
                f"[RESOURCE GUARD] WARNING: Memory at {mem_gb:.2f} GB "
                f"({mem_gb / max_memory_gb * 100:.0f}% of limit)"
            )

        time.sleep(check_interval)

    print(f"[RESOURCE GUARD] Process exited with code {proc.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resource-limited command runner")
    parser.add_argument(
        "--max-gb",
        type=float,
        default=8.0,
        help="Maximum memory in GB (default: 8)",
    )
    parser.add_argument(
        "--check-interval",
        type=float,
        default=0.5,
        help="Memory check interval in seconds (default: 0.5)",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run (after --)",
    )

    args = parser.parse_args()

    if not args.command or args.command[0] == "--":
        args.command = args.command[1:] if args.command else []

    if not args.command:
        print("Error: No command specified", file=sys.stderr)
        print("Usage: resource_guard.py --max-gb 8 -- pytest ...", file=sys.stderr)
        return 1

    print(f"[RESOURCE GUARD] Running: {' '.join(args.command)}")
    print(f"[RESOURCE GUARD] Memory limit: {args.max_gb} GB")

    # Start process in new process group for clean termination
    proc = subprocess.Popen(
        args.command,
        preexec_fn=os.setsid,
    )

    # Start monitor thread
    monitor_thread = threading.Thread(
        target=monitor_process,
        args=(proc, args.max_gb, args.check_interval),
        daemon=True,
    )
    monitor_thread.start()

    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait(timeout=5)
        return 130


if __name__ == "__main__":
    sys.exit(main())
