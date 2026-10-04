"""Command-line interface for fim."""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .events import Alert
from .sample_data import DEFAULT_SAMPLE_DIR, apply_demo_changes, create_sample_folder
from .scanner import build_baseline, diff_snapshots, scan_directory
from .storage import (
    append_alert_log,
    baseline_exists,
    default_store_dir,
    load_baseline,
    read_alert_log,
    save_baseline,
)
from .watcher import DEFAULT_DEBOUNCE_SECONDS, FileWatcher


def _resolve_store(dir_path: str, store_arg: Optional[str]) -> Path:
    return Path(store_arg) if store_arg else default_store_dir(dir_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fim",
        description="A small, explainable file integrity monitor. Not a replacement "
                     "for a production FIM product — see README.",
    )
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Establish a baseline for a directory")
    p_init.add_argument("--dir", default=DEFAULT_SAMPLE_DIR, help=f"Directory to baseline (default: {DEFAULT_SAMPLE_DIR})")
    p_init.add_argument("--store", help="Where to keep the baseline/log (default: <dir>/.fim)")

    p_check = sub.add_parser("check", help="One-shot hash comparison against the saved baseline")
    p_check.add_argument("--dir", default=DEFAULT_SAMPLE_DIR)
    p_check.add_argument("--store", help="Where the baseline/log live (default: <dir>/.fim)")
    p_check.add_argument("--update", action="store_true", help="Save the current state as the new baseline afterward")
    p_check.add_argument("--json", metavar="PATH", help="Also write alerts as JSON to PATH")

    p_watch = sub.add_parser("watch", help="Real-time monitoring via filesystem events + hash confirmation")
    p_watch.add_argument("--dir", default=DEFAULT_SAMPLE_DIR)
    p_watch.add_argument("--store", help="Where the baseline/log live (default: <dir>/.fim)")
    p_watch.add_argument("--debounce", type=float, default=DEFAULT_DEBOUNCE_SECONDS,
                          help=f"Seconds of quiet before a change is resolved (default: {DEFAULT_DEBOUNCE_SECONDS})")
    p_watch.add_argument("--duration", type=float, default=None,
                          help="Stop automatically after this many seconds (default: run until Ctrl-C)")

    p_demo = sub.add_parser(
        "demo",
        help="Set up (or reset) the sample folder, baseline it, apply a scripted set of "
             "changes, then run a check so every alert type is demonstrated in one command",
    )
    p_demo.add_argument("--dir", default=DEFAULT_SAMPLE_DIR)
    p_demo.add_argument("--store", help="Where the baseline/log live (default: <dir>/.fim)")

    p_log = sub.add_parser("log", help="Print the stored alert log")
    p_log.add_argument("--dir", default=DEFAULT_SAMPLE_DIR)
    p_log.add_argument("--store", help="Where the baseline/log live (default: <dir>/.fim)")

    return parser


def _print_alerts(alerts: List[Alert]) -> None:
    if not alerts:
        print("No changes detected.")
        return
    for a in alerts:
        print(f"[{a.timestamp.isoformat(timespec='seconds')}] {a.kind.upper():<13} {a.path} — {a.message}")


def cmd_init(args) -> int:
    store = _resolve_store(args.dir, args.store)
    baseline, result = build_baseline(args.dir, exclude_dirs=[store])
    save_baseline(baseline, store)
    print(f"Baseline established for '{args.dir}': {len(baseline.files)} file(s) recorded.")
    if result.inaccessible:
        print(f"  {len(result.inaccessible)} path(s) were skipped as inaccessible:")
        for p in result.inaccessible:
            print(f"    - {p}")
    print(f"Baseline stored at: {store}")
    return 0


def cmd_check(args) -> int:
    store = _resolve_store(args.dir, args.store)
    if not baseline_exists(store):
        print(f"No baseline found at {store}. Run `fim init --dir {args.dir}` first.", file=sys.stderr)
        return 1

    baseline = load_baseline(store)
    current = scan_directory(args.dir, exclude_dirs=[store])
    alerts = diff_snapshots(baseline.files, current.files)

    for relpath in current.inaccessible:
        alerts.append(Alert(
            kind="inaccessible", path=relpath,
            timestamp=datetime.now(),
            message=f"Could not read {relpath} during check",
        ))

    _print_alerts(alerts)
    append_alert_log(alerts, store)

    if args.json:
        import json
        Path(args.json).write_text(
            json.dumps([a.to_dict() for a in alerts], indent=2), encoding="utf-8"
        )
        print(f"(alerts also written to {args.json})")

    if args.update:
        new_baseline, _ = build_baseline(args.dir, exclude_dirs=[store])
        save_baseline(new_baseline, store)
        print("Baseline updated to current state.")

    return 0


def cmd_watch(args) -> int:
    store = _resolve_store(args.dir, args.store)
    if not baseline_exists(store):
        print(f"No baseline found at {store}. Run `fim init --dir {args.dir}` first.", file=sys.stderr)
        return 1

    baseline = load_baseline(store)
    collected: List[Alert] = []

    def on_alert(alert: Alert) -> None:
        collected.append(alert)
        print(f"[{alert.timestamp.isoformat(timespec='seconds')}] {alert.kind.upper():<13} {alert.path} — {alert.message}")
        append_alert_log([alert], store)

    watcher = FileWatcher(root=Path(args.dir), store_dir=store, baseline=baseline,
                           debounce_seconds=args.debounce, on_alert=on_alert)

    print(f"Watching '{args.dir}' (debounce={args.debounce}s). Press Ctrl-C to stop.")
    if args.duration:
        import time
        watcher.start()
        end = time.monotonic() + args.duration
        try:
            while time.monotonic() < end:
                watcher.process_ready()
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            watcher.stop()
    else:
        watcher.run_forever()

    save_baseline(watcher.baseline, store)
    print(f"Stopped. {len(collected)} alert(s) recorded this session.")
    return 0


def cmd_demo(args) -> int:
    print(f"Setting up sample folder at '{args.dir}' ...")
    create_sample_folder(args.dir)

    store = _resolve_store(args.dir, args.store)
    baseline, result = build_baseline(args.dir, exclude_dirs=[store])
    save_baseline(baseline, store)
    print(f"Baseline established: {len(baseline.files)} file(s).")
    if result.inaccessible:
        print(f"Noted {len(result.inaccessible)} inaccessible path(s) at baseline time "
              f"(e.g. the demo's intentionally-broken symlink): {result.inaccessible}")

    print("\nApplying a scripted set of changes (create, modify, delete) ...\n")
    apply_demo_changes(args.dir)

    current = scan_directory(args.dir, exclude_dirs=[store])
    alerts = diff_snapshots(baseline.files, current.files)
    for relpath in current.inaccessible:
        alerts.append(Alert(
            kind="inaccessible", path=relpath,
            timestamp=datetime.now(),
            message=f"Could not read {relpath}",
        ))

    _print_alerts(alerts)
    append_alert_log(alerts, store)
    print(f"\nDemo complete. Alert log: {store}/alerts.log.jsonl")
    return 0


def cmd_log(args) -> int:
    store = _resolve_store(args.dir, args.store)
    entries = read_alert_log(store)
    if not entries:
        print("No alerts logged yet.")
        return 0
    for e in entries:
        print(f"[{e['timestamp']}] {e['kind'].upper():<13} {e['path']} — {e['message']}")
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    dispatch = {
        "init": cmd_init,
        "check": cmd_check,
        "watch": cmd_watch,
        "demo": cmd_demo,
        "log": cmd_log,
    }
    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
