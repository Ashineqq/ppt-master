#!/usr/bin/env python3
"""
PPT Master - Phase Clock and Dispatch Receipt

Records per-phase start times and parallel-dispatch evidence so the intake,
acquisition, and page-authoring budgets of the route are auditable instead of
advisory. Writes one JSON receipt; every subcommand reads and rewrites it.

Usage:
    python3 scripts/phase_clock.py start <project_path> <phase> [--state PATH]
    python3 scripts/phase_clock.py dispatch <project_path> <phase> --workers N --files a,b [--state PATH]
    python3 scripts/phase_clock.py check <project_path> <phase> [--budget 180] [--min-workers N] [--json] [--state PATH]
    python3 scripts/phase_clock.py report <project_path> [--json] [--state PATH]

Examples:
    python3 scripts/phase_clock.py start projects/demo research --state projects/.phase_budget.json
    python3 scripts/phase_clock.py check projects/demo research --budget 180 --state projects/.phase_budget.json
    python3 scripts/phase_clock.py dispatch projects/demo pages --workers 4 --files 02_a.svg,05_b.svg
    python3 scripts/phase_clock.py report projects/demo

Exit codes for check:
    0  inside the budget and, when required, enough dispatched workers
    1  over the budget
    2  the phase was never started
    3  fewer workers recorded than --min-workers

Dependencies:
    None (only uses standard library)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

DEFAULT_BUDGET_SECONDS = 180


def _receipt_path(project_path: Path, state: str | None) -> Path:
    if state:
        return Path(state)
    return project_path / "validation" / "phase_budget.json"


def _load(path: Path) -> dict:
    if not path.exists():
        return {"schema": "ppt-master.phase-budget.v1", "phases": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": "ppt-master.phase-budget.v1", "phases": {}}
    if not isinstance(data.get("phases"), dict):
        data["phases"] = {}
    return data


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _phase(data: dict, name: str) -> dict:
    return data["phases"].setdefault(name, {})


def cmd_start(args) -> int:
    path = _receipt_path(Path(args.project_path), args.state)
    data = _load(path)
    entry = _phase(data, args.phase)
    entry["started_at"] = time.time()
    entry["started_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(entry["started_at"]))
    _save(path, data)
    print(f"[PHASE] {args.phase} started {entry['started_iso']} -> {path}")
    return 0


def cmd_dispatch(args) -> int:
    path = _receipt_path(Path(args.project_path), args.state)
    data = _load(path)
    files = [item.strip() for item in (args.files or "").split(",") if item.strip()]
    entry = _phase(data, args.phase)
    entry.setdefault("dispatches", []).append({
        "workers": max(int(args.workers), 1),
        "files": files,
        "dispatched_at": time.time(),
    })
    _save(path, data)
    total = sum(item["workers"] for item in entry["dispatches"])
    print(f"[PHASE] {args.phase} dispatch recorded: {args.workers} worker(s), {len(files)} file(s), {total} worker(s) total")
    return 0


def cmd_check(args) -> int:
    path = _receipt_path(Path(args.project_path), args.state)
    data = _load(path)
    entry = data["phases"].get(args.phase)
    if not entry or "started_at" not in entry:
        print(f"[PHASE] {args.phase}: NOT STARTED — run 'start' before the phase")
        return 2
    elapsed = time.time() - entry["started_at"]
    workers = sum(item["workers"] for item in entry.get("dispatches", []))
    over = elapsed > args.budget
    short = args.min_workers is not None and workers < args.min_workers
    if args.json:
        print(json.dumps({
            "phase": args.phase,
            "elapsed_seconds": round(elapsed, 1),
            "budget_seconds": args.budget,
            "workers": workers,
            "min_workers": args.min_workers,
            "over_budget": over,
            "workers_short": short,
        }, ensure_ascii=False))
    else:
        state = "OVER" if over else "OK"
        print(f"[PHASE] {args.phase}: {elapsed:.0f}s / {args.budget}s {state}; workers={workers}"
              + (f" (min {args.min_workers})" if args.min_workers is not None else ""))
    if over:
        return 1
    if short:
        return 3
    return 0


def cmd_report(args) -> int:
    path = _receipt_path(Path(args.project_path), args.state)
    data = _load(path)
    rows = []
    for name, entry in sorted(data.get("phases", {}).items()):
        started = entry.get("started_at")
        workers = sum(item["workers"] for item in entry.get("dispatches", []))
        rows.append({
            "phase": name,
            "elapsed_seconds": round(time.time() - started, 1) if started else None,
            "workers": workers,
            "files": [f for item in entry.get("dispatches", []) for f in item.get("files", [])],
        })
    if args.json:
        print(json.dumps({"receipt": str(path), "phases": rows}, ensure_ascii=False))
        return 0
    print(f"[PHASE] receipt: {path}")
    for row in rows:
        elapsed = "not started" if row["elapsed_seconds"] is None else f"{row['elapsed_seconds']:.0f}s"
        print(f"  {row['phase']:<12} {elapsed:>10}  workers={row['workers']}  files={len(row['files'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase clock and parallel-dispatch receipt for PPT Master routes.")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Record the phase start time")
    start.add_argument("project_path")
    start.add_argument("phase")
    start.add_argument("--state", default=None)
    start.set_defaults(func=cmd_start)

    dispatch = sub.add_parser("dispatch", help="Record how many workers were dispatched over which files")
    dispatch.add_argument("project_path")
    dispatch.add_argument("phase")
    dispatch.add_argument("--workers", type=int, required=True)
    dispatch.add_argument("--files", default="")
    dispatch.add_argument("--state", default=None)
    dispatch.set_defaults(func=cmd_dispatch)

    check = sub.add_parser("check", help="Check elapsed time and dispatch count against the phase contract")
    check.add_argument("project_path")
    check.add_argument("phase")
    check.add_argument("--budget", type=int, default=DEFAULT_BUDGET_SECONDS)
    check.add_argument("--min-workers", type=int, default=None)
    check.add_argument("--json", action="store_true")
    check.add_argument("--state", default=None)
    check.set_defaults(func=cmd_check)

    report = sub.add_parser("report", help="Print the receipt")
    report.add_argument("project_path")
    report.add_argument("--json", action="store_true")
    report.add_argument("--state", default=None)
    report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
