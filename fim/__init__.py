"""
fim — a small, portfolio-scale file integrity monitor.

WHAT THIS IS
    Point it at a directory. It records a cryptographic-hash baseline
    of every file in it, then detects and clearly reports created,
    modified, and deleted files two ways:

      - a one-shot hash comparison ("fim check") against the saved
        baseline — the classic file-integrity-monitoring approach
        (think a small, explainable Tripwire/AIDE-style check).
      - real-time filesystem events ("fim watch", via the `watchdog`
        library) for immediate alerts as changes happen, with rapid
        repeated changes to the same file debounced into one alert
        rather than a flood.

    Every alert carries a timestamp, the kind of change, the path
    involved, and (for modifications) the old and new hash — nothing
    here is a silent pass/fail.

WHAT THIS IS NOT
    Not a replacement for a real FIM product (Tripwire, AIDE, OSSEC,
    Wazuh, ...). It does not verify file *permissions*, ownership,
    extended attributes, or directory structure beyond presence; it
    does not detect in-memory tampering, and it trusts its own stored
    baseline (so an attacker who can rewrite the baseline file can
    hide their tracks — see the README's Limitations section).

SAFETY / HOUSEKEEPING
    The monitor's own baseline file and alert log live in a dedicated
    store directory that is always excluded from the scan/watch of the
    target directory, specifically to avoid the tool endlessly
    "detecting" its own bookkeeping writes as changes to the thing it's
    watching.
"""

__version__ = "1.0.0"
