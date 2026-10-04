# fim — a small, explainable file integrity monitor

Establishes a cryptographic-hash baseline for a directory, then
detects **created**, **modified**, and **deleted** files two
complementary ways — a one-shot hash comparison against the baseline,
and real-time filesystem events confirmed by re-hashing — and reports
every change with a timestamp, the kind of change, and the exact
before/after evidence.

> **This is a learning/portfolio prototype, not a production FIM
> product** (Tripwire, AIDE, OSSEC, Wazuh, ...). See
> [Limitations](#limitations).

## Quick start

```bash
pip install -e .

# Runs the entire demo in one command: creates a sample folder, baselines
# it, applies a scripted create + modify + delete, and shows all three alerts:
python3 -m fim demo
```

That's it — `fim demo` defaults to `sample_data/watched_demo` and needs
no setup. Everything below explains the pieces it just ran together.

## Manual usage

```bash
# 1. Point it at any directory and establish a baseline:
python3 -m fim init --dir path/to/your/folder

# 2. Change some files, then check what's different:
python3 -m fim check --dir path/to/your/folder

# 3. Accept the current state as the new baseline (optional):
python3 -m fim check --dir path/to/your/folder --update

# 4. Or monitor in real time instead of checking manually:
python3 -m fim watch --dir path/to/your/folder

# 5. Review everything that's ever been logged:
python3 -m fim log --dir path/to/your/folder
```

Every command accepts `--dir` (default: the bundled sample folder,
`sample_data/watched_demo`) and `--store` (default: `<dir>/.fim` — see
[Where things are stored](#where-things-are-stored-and-why-its-excluded)).

## How detection works — two complementary modes

**`fim check`** — a one-shot hash sweep. Walks the directory, hashes
every file, and diffs the result against the saved baseline by content
hash (not by mtime/size, so a file rewritten with identical bytes is
correctly treated as unchanged, and a change that didn't touch mtime
is still caught). This is the classic periodic-integrity-check pattern
— run it by hand, from cron, or in CI.

**`fim watch`** — real-time, via the `watchdog` library (inotify on
Linux, FSEvents on macOS, ReadDirectoryChangesW on Windows).
Filesystem events tell the monitor *when* a path might have changed;
it doesn't trust the raw event type, though — it re-hashes that file
and compares against the live baseline to decide definitively *what*
happened. This combination (events for timing, hashes for truth) is
what makes rapid repeated changes and no-op edits handled sensibly —
see below.

## Handling rapid repeated changes

Editors and build tools routinely fire several raw filesystem events
for what a person would call "one edit" (a write, a flush, a separate
metadata touch), and atomic-save patterns write a temp file and delete
it. `fim watch` never reacts to a raw event directly: touching a path
just resets a per-path "quiet timer" (`--debounce`, default 0.75s). A
background flush only resolves a path once it's gone quiet, hashes it
*once*, and emits at most one alert for the whole burst:

- **Several rapid modifications** → one `modified` alert, using the
  final content, not an intermediate state.
- **A file created and deleted again within the window** (an atomic-save
  temp file) → no alert at all; there was no net change.
- **A file edited and then reverted to its original content within the
  window** → no alert; the hash matches the baseline again.

## Handling inaccessible files

A file can become unreadable for plenty of reasons — permissions, a
race where it's deleted between the event and the hash attempt, or a
broken symlink. `fim` never lets one bad file crash a scan or a watch
session: `hashing.py` catches every such case and the scanner/watcher
report it as its own alert kind, `inaccessible`, with the specific
reason, instead of raising. The bundled sample folder includes a
**broken symlink** specifically to demonstrate this reliably — unlike
a permission-denied file, a broken symlink is unreadable regardless of
which user runs the demo (including root).

## Where things are stored, and why it's excluded

Each monitored directory gets its own store directory — by default
`<dir>/.fim/`, holding `baseline.json` and `alerts.log.jsonl`. That
store directory is **always** excluded from the directory's own
scan/watch (see `scanner.is_excluded` and `FileWatcher`'s
`exclude_dirs`), specifically so the tool never reports writing its own
baseline or appending to its own log as a change to the thing it's
watching — which would otherwise be an infinite feedback loop every
single time an alert fires.

## Exact steps to demonstrate each alert type

All of this is exactly what `fim demo` automates, laid out manually:

```bash
# Setup
python3 -c "from fim.sample_data import create_sample_folder; create_sample_folder('sample_data/watched_demo')"
python3 -m fim init --dir sample_data/watched_demo

# CREATED
echo "a new file" > sample_data/watched_demo/new_file.txt
python3 -m fim check --dir sample_data/watched_demo
#   -> CREATED  new_file.txt

# MODIFIED
echo "extra line" >> sample_data/watched_demo/notes.md
python3 -m fim check --dir sample_data/watched_demo
#   -> MODIFIED notes.md

# DELETED
rm sample_data/watched_demo/config.ini
python3 -m fim check --dir sample_data/watched_demo
#   -> DELETED  config.ini

# INACCESSIBLE (the sample folder's broken symlink is always reported)
python3 -m fim check --dir sample_data/watched_demo
#   -> INACCESSIBLE broken_link.txt

# Same four, live, via the watcher instead of polling with `check`:
python3 -m fim watch --dir sample_data/watched_demo --duration 10 &
sleep 1 && echo "live" > sample_data/watched_demo/live_demo.txt
sleep 1 && echo "more" >> sample_data/watched_demo/notes.md
wait
```

## Thresholds and defaults

| Setting | Default | Where |
|---|---|---|
| Debounce window (`--debounce`) | 0.75s | `fim watch` |
| Hash algorithm | SHA-256 | `hashing.py` |
| Read chunk size | 64 KiB | `hashing.py` |
| Comparison basis | content hash (not mtime/size) | `scanner.diff_snapshots` |

## False positives / what legitimately changes a file

- A build tool, package manager, or editor rewriting a file with
  identical content still updates its mtime — this tool correctly
  does **not** alert on that (hash comparison, not mtime), but if you
  add your own mtime-based checks on top, expect noise there.
- Log rotation, lock files, and `.swp`/`.tmp` editor artifacts inside
  the monitored directory will register as ordinary created/deleted
  files unless you point `--dir` at something that excludes them (this
  prototype has no glob-based ignore list beyond its own store
  directory — see Limitations).
- A legitimate software update or config change will (correctly) fire
  a `modified` alert — this tool cannot distinguish "an authorized
  change" from "a suspicious one"; that judgment is still yours.

## Limitations

- **Trusts its own baseline.** `baseline.json` is a plain file on disk.
  Anyone with write access to the store directory can rewrite it to
  hide a change — there's no separate signing, remote storage, or
  write-once protection. A production FIM typically ships the baseline
  read-only or off-host for exactly this reason.
- **Content only.** Permissions, ownership, extended attributes, and
  directory structure (beyond a path's presence) are not part of the
  comparison — two files with identical bytes but different modes
  look identical to this tool.
- **No ignore-pattern list** beyond the tool's own store directory —
  no built-in `.gitignore`-style exclusions for things like `__pycache__`
  or editor swap files inside the monitored tree.
- **`fim watch` depends on the OS's native file-watching API** (via
  `watchdog`); on filesystems or mount types that don't support native
  events (some network filesystems, some container volume mounts),
  live events may be delayed, missed, or require `watchdog`'s polling
  fallback, which it selects automatically but less promptly.
- **No cryptographic signing of the alert log** — `alerts.log.jsonl` is
  a plain append-only JSON-lines file; it's evidence for a human to
  read, not tamper-evident audit output.
- **Single-machine, single-directory tool.** No remote baselines,
  no multi-host aggregation, no built-in alerting beyond stdout/the log
  file.

## Running the tests

```bash
pip install -e ".[dev]"
python3 -m pytest -v
```

59 tests cover hashing (including large files, broken symlinks, and
missing files), baseline/alert-log persistence, the scan/diff logic
(every alert kind, multi-change diffs, exclusion), the CLI end to end,
the sample-data generator, and the debounced watcher — including one
test (`@pytest.mark.integration`) that drives a **real** `watchdog`
`Observer` against real filesystem events rather than calling the
internal API directly, to prove the whole real-time path actually
works end to end.

## Technologies used

- Python 3 standard library: `hashlib`, `pathlib`, `json`, `threading`,
  `dataclasses`, `argparse`.
- **`watchdog`** for cross-platform real-time filesystem events
  (inotify / FSEvents / ReadDirectoryChangesW).
- **pytest**, including a real-observer integration test (no mocked
  filesystem events).

## Portfolio notes

This project demonstrates integrity-verification fundamentals (hash
baselines, content-based diffing) combined with real-time event
handling and the debouncing a real-world watcher needs to be usable
rather than noisy — plus the habit of being explicit about a tool's
own trust boundaries (the baseline-trust limitation above) rather than
presenting it as more authoritative than it is.

**Demo / screenshot suggestions:**
- Run `fim demo` and screenshot the four-line alert output —
  created/modified/deleted/inaccessible, all from one command.
- Open `examples/sample_alert_log.json` to show the full before/after
  hash evidence recorded per alert.
- Run the rapid-repeated-edit scenario live (`for i in 1 2 3 4 5; do
  echo $i >> sample_data/watched_demo/notes.md; done` while `fim watch`
  is running) and point out it produces exactly **one** `modified`
  alert, not five.
- Show `fim check` run twice in a row after `--update` — the second run
  printing "No changes detected" is the clearest proof the baseline
  comparison is doing real content comparison, not just reacting to any
  filesystem touch.
