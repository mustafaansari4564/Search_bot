"""
start.py — Single entry point for KeritCloud deployment.
Set your startup command to:  python start.py

Sequence on first deploy (no database yet):
  1. Run indexer.py → crawls Discord library, builds library.db
  2. Run bot.py     → starts the bot (loads BM25 from library.db)

Sequence on every restart after that (database already exists):
  1. Skip indexer  → library.db already has data
  2. Run bot.py    → loads BM25 from library.db and starts immediately

To add new threads after deploy → use /reindex-new inside Discord.
To rebuild everything from scratch → use /reindex inside Discord.
"""

# ── Force unbuffered output (must happen before anything else) ─────────────────
# Without this, print() statements sit in a buffer and never reach KeritCloud's
# logs until the buffer fills or the process exits — making it look like the
# bot is "not responding" even when it's working fine or has already crashed.
import os
os.environ.setdefault("PYTHONUNBUFFERED", "1")   # also inherited by subprocess.run and os.execv

import sys
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

import subprocess

DB_PATH = "./library.db"


def _banner(text: str) -> None:
    line = "─" * 52
    print(f"\n{line}", flush=True)
    print(f"  {text}", flush=True)
    print(f"{line}\n", flush=True)


def db_has_data() -> bool:
    """
    Returns True if library.db exists and contains indexed content.
    An empty schema file is ~8 KB — anything above that has real data.
    """
    if not os.path.exists(DB_PATH):
        return False
    return os.path.getsize(DB_PATH) > 8_192


def run_indexer() -> None:
    """Run indexer.py as a subprocess and exit if it fails."""
    _banner("Step 1 — Building Library Index")
    print("[Start] Crawling Discord library…", flush=True)
    print("[Start] This can take 15–30 min for large libraries.\n", flush=True)

    # PYTHONUNBUFFERED is already set in os.environ above, so the child
    # process inherits it automatically and its logs stream live too.
    result = subprocess.run([sys.executable, "-u", "indexer.py"])

    if result.returncode != 0:
        print(
            f"\n[Start] ❌ Indexer exited with code {result.returncode}.\n"
            f"[Start]    Check the logs above for details.",
            flush=True,
        )
        sys.exit(result.returncode)

    print("\n[Start] ✅ Library indexed successfully.", flush=True)


def start_bot() -> None:
    """Replace current process with bot.py using os.execv."""
    _banner("Step 2 — Starting Bot")
    # os.execv replaces the current process so KeritCloud's
    # process manager sees bot.py as the running process.
    # It inherits this process's environment, including PYTHONUNBUFFERED.
    os.execv(sys.executable, [sys.executable, "-u", "bot.py"])


def main() -> None:
    print("\n" + "═" * 52, flush=True)
    print("  Theological Discourse Library Bot", flush=True)
    print("═" * 52, flush=True)

    if db_has_data():
        size_kb = os.path.getsize(DB_PATH) // 1024
        print(f"\n[Start] Library database found — {size_kb} KB", flush=True)
        print("[Start] Skipping indexer. BM25 will load on bot startup.", flush=True)
        print("[Start] Use /reindex-new in Discord to add new threads.", flush=True)
    else:
        print("\n[Start] No library database found (first deploy).", flush=True)
        run_indexer()

    start_bot()


if __name__ == "__main__":
    main()
    