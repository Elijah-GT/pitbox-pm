"""Production entry point, run by the CarHub scheduled task at boot.

Task Scheduler gives a process no console and no way to redirect its output, so
logging is configured here rather than left to the shell. Everything lands in
deploy/logs/pitbox.log, rotated at 2 MB and kept for five generations, which is
enough to answer "was it up on Tuesday" without ever needing to be pruned.

    python deploy/serve.py

Environment (all optional):
    PITBOX_HOST   default 127.0.0.1 -- localhost only, the right default when a
                  Cloudflare Tunnel is in front. Set 0.0.0.0 for LAN/Tailscale.
    PITBOX_PORT   default 8000
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_DIR / "deploy" / "logs"

# The task may start us with an arbitrary working directory (SYSTEM starts in
# system32), so pin both the import path and the cwd. Relative settings such as
# sqlite:///./pitbox.db resolve against the cwd, and getting this wrong creates
# a second, empty database somewhere surprising.
sys.path.insert(0, str(PROJECT_DIR))
os.chdir(PROJECT_DIR)


def configure_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_DIR / "pitbox.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s  %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # uvicorn installs its own handlers by default; we pass log_config=None below
    # so these are the only ones and nothing is written to a console that is not
    # there. Access logs stay at WARNING or the file fills with routine 200s.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def main() -> int:
    configure_logging()
    log = logging.getLogger("pitbox")

    host = os.environ.get("PITBOX_HOST", "127.0.0.1")
    port = int(os.environ.get("PITBOX_PORT", "8000"))

    log.info("starting CarHub from %s on %s:%s", PROJECT_DIR, host, port)

    try:
        import uvicorn
    except ImportError:
        log.exception("uvicorn is not installed -- is the task pointing at .venv's python?")
        return 1

    try:
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            log_config=None,  # keep the handlers configured above
            access_log=True,
        )
    except Exception:
        # Without this the task just exits with a code and no explanation.
        log.exception("CarHub stopped with an unhandled error")
        return 1

    log.info("CarHub stopped cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
