"""Background worker. Runs inside the web process (thread mode) or on its own:

    python -m app.jobs.worker
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time

from app.config import get_settings
from app.db.base import SessionLocal
from app.jobs.queue import claim_next, recover_all_running, recover_stale, run_job

log = logging.getLogger(__name__)


class Worker:
    def __init__(self, concurrency: int = 1, poll_seconds: float = 1.0):
        self.concurrency = max(1, concurrency)
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"

    def start(self) -> None:
        import app.jobs.handlers  # noqa: F401  (register handlers)

        db = SessionLocal()
        try:
            n = recover_all_running(db)
            if n:
                log.info("requeued %s interrupted job(s)", n)
        finally:
            db.close()
        for i in range(self.concurrency):
            t = threading.Thread(target=self._loop, name=f"studio-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=timeout)

    def _loop(self) -> None:
        last_recover = time.monotonic()
        while not self._stop.is_set():
            try:
                db = SessionLocal()
                try:
                    if time.monotonic() - last_recover > 60:
                        recover_stale(db)
                        last_recover = time.monotonic()
                    job = claim_next(db, self.worker_id)
                finally:
                    db.close()
                if job is None:
                    self._stop.wait(self.poll_seconds)
                    continue
                run_job(job.id, self.worker_id)
            except Exception:  # never let the worker thread die
                log.exception("worker loop error")
                self._stop.wait(2.0)


def main() -> None:
    from app.core.logging import configure_logging
    from app.db.migrate import upgrade_database

    s = get_settings()
    configure_logging(s.studio_log_level, s.studio_log_json)
    upgrade_database()
    w = Worker(concurrency=s.worker_concurrency)
    w.start()
    log.info("worker started (%s threads)", w.concurrency)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        w.stop()


if __name__ == "__main__":
    main()
