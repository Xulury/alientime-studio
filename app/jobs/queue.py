"""Persistent job queue stored in the database.

Jobs survive restarts: a job left "running" by a crashed or stopped process is put back in the
queue (or failed once it has used its attempts). Idempotency keys stop duplicate work, e.g. the same
publish request clicked twice.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.base import SessionLocal, utcnow
from app.db.models import Job

log = logging.getLogger(__name__)

ACTIVE = ("pending", "running")
FINAL = ("completed", "failed", "cancelled")


class PermanentJobError(Exception):
    """The job cannot succeed by retrying (bad input, gate failed, not authorised)."""


class JobCancelled(Exception):
    pass


HandlerFn = Callable[["JobContext"], Optional[dict[str, Any]]]
_HANDLERS: dict[str, HandlerFn] = {}
JOB_LABELS: dict[str, str] = {}


def handler(job_type: str, label: str):
    def deco(fn: HandlerFn) -> HandlerFn:
        _HANDLERS[job_type] = fn
        JOB_LABELS[job_type] = label
        return fn
    return deco


def get_handler(job_type: str) -> HandlerFn | None:
    return _HANDLERS.get(job_type)


def enqueue(
    db: Session,
    job_type: str,
    *,
    watch_id: str | None = None,
    asset_id: str | None = None,
    channel: str | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    run_after: datetime | None = None,
    max_attempts: int | None = None,
    created_by: str | None = None,
) -> Job:
    if idempotency_key:
        existing = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
        if existing is not None:
            if existing.status in ("failed", "cancelled"):
                existing.status = "pending"
                existing.attempts = 0
                existing.error = None
                existing.progress = 0.0
                existing.progress_message = "Queued again"
                existing.cancel_requested = False
                existing.run_after = run_after or utcnow()
                existing.payload = payload or existing.payload
                existing.finished_at = None
            return existing
    job = Job(
        type=job_type,
        watch_id=watch_id,
        asset_id=asset_id,
        channel=channel,
        payload=payload or {},
        idempotency_key=idempotency_key,
        run_after=run_after or utcnow(),
        max_attempts=max_attempts or get_settings().job_max_attempts,
        created_by=created_by,
        progress_message="Queued",
    )
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session, worker_id: str) -> Job | None:
    now = utcnow()
    candidates = db.scalars(
        select(Job.id).where(Job.status == "pending", Job.run_after <= now).order_by(Job.created_at).limit(5)
    ).all()
    for jid in candidates:
        res = db.execute(
            update(Job)
            .where(Job.id == jid, Job.status == "pending")
            .values(status="running", locked_by=worker_id, started_at=now, heartbeat_at=now,
                    attempts=Job.attempts + 1, progress_message="Starting")
        )
        db.commit()
        if res.rowcount == 1:
            return db.get(Job, jid)
    return None


def recover_stale(db: Session) -> int:
    """Requeue jobs whose worker stopped (application restart or crash)."""
    cutoff = utcnow() - timedelta(minutes=get_settings().job_stale_minutes)
    stale = db.scalars(select(Job).where(Job.status == "running")).all()
    n = 0
    for job in stale:
        if job.heartbeat_at and job.heartbeat_at > cutoff:
            continue
        n += 1
        if job.attempts < job.max_attempts:
            job.status = "pending"
            job.progress_message = "Resumed after the application restarted"
        else:
            job.status = "failed"
            job.error = "Interrupted when the application stopped, and no attempts remain."
            job.finished_at = utcnow()
    db.commit()
    return n


def recover_all_running(db: Session) -> int:
    """At start-up nothing can be running yet, so every 'running' job was interrupted."""
    jobs = db.scalars(select(Job).where(Job.status == "running")).all()
    for job in jobs:
        job.heartbeat_at = None
    db.commit()
    return recover_stale(db)


def cancel(db: Session, job: Job) -> Job:
    if job.status == "pending":
        job.status = "cancelled"
        job.finished_at = utcnow()
        job.progress_message = "Cancelled"
    elif job.status == "running":
        job.cancel_requested = True
        job.progress_message = "Cancelling…"
    return job


def retry(db: Session, job: Job) -> Job:
    if job.status in ("failed", "cancelled"):
        job.status = "pending"
        job.attempts = 0
        job.error = None
        job.cancel_requested = False
        job.progress = 0.0
        job.progress_message = "Queued for retry"
        job.run_after = utcnow()
        job.finished_at = None
    return job


class JobContext:
    """Passed to handlers.

    `progress()` commits the handler's session: work done so far (e.g. a finished pipeline stage) is
    saved together with the progress update. Committing in the same session avoids SQLite lock contention
    between a long-running job and its own progress writes.
    """

    def __init__(self, job: Job, db: Session):
        self.job = job
        self.db = db
        self.payload = dict(job.payload or {})

    def progress(self, pct: float, message: str | None = None) -> None:
        pct = max(0.0, min(100.0, float(pct)))
        j = self.db.get(Job, self.job.id)
        if j is None:
            return
        j.progress = pct
        if message:
            j.progress_message = message[:300]
        j.heartbeat_at = utcnow()
        self.db.commit()
        self.check_cancelled()

    def check_cancelled(self) -> None:
        j = self.db.get(Job, self.job.id)
        if j is None:
            return
        self.db.refresh(j, attribute_names=["cancel_requested"])
        if j.cancel_requested:
            raise JobCancelled()


def _backoff_seconds(attempt: int) -> int:
    return min(300, 5 * (2 ** max(0, attempt - 1)))


def run_job(job_id: str, worker_id: str = "inline") -> Job:
    """Run one claimed job to completion (or failure). Returns the final job row."""
    from app.core.lifecycle import refresh_status
    from app.db.models import Watch

    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        assert job is not None
        fn = get_handler(job.type)
        ctx = JobContext(job, db)
        try:
            if fn is None:
                raise PermanentJobError(f"Unknown job type: {job.type}")
            result = fn(ctx) or {}
            db.commit()
            job = db.get(Job, job_id)
            job.status = "completed"
            job.result = result
            job.progress = 100.0
            job.progress_message = result.get("message", "Done") if isinstance(result, dict) else "Done"
            job.finished_at = utcnow()
            job.error = None
        except JobCancelled:
            db.rollback()
            job = db.get(Job, job_id)
            job.status = "cancelled"
            job.progress_message = "Cancelled"
            job.finished_at = utcnow()
        except PermanentJobError as e:
            db.rollback()
            job = db.get(Job, job_id)
            job.status = "failed"
            job.error = str(e)[:4000]
            job.progress_message = "Failed"
            job.finished_at = utcnow()
        except Exception as e:  # retryable
            db.rollback()
            log.exception("job %s (%s) failed", job_id, job.type, extra={"job_id": job_id})
            job = db.get(Job, job_id)
            msg = f"{type(e).__name__}: {e}"[:4000]
            if job.attempts < job.max_attempts:
                job.status = "pending"
                job.error = msg
                job.run_after = utcnow() + timedelta(seconds=_backoff_seconds(job.attempts))
                job.progress_message = f"Will retry (attempt {job.attempts + 1} of {job.max_attempts})"
            else:
                job.status = "failed"
                job.error = msg
                job.progress_message = "Failed"
                job.finished_at = utcnow()
        db.commit()
        if job.watch_id:
            w = db.get(Watch, job.watch_id)
            if w is not None:
                refresh_status(db, w)
                db.commit()
        return job
    finally:
        db.close()


def run_pending(max_jobs: int = 100, include_delayed: bool = False) -> list[Job]:
    """Synchronously process queued jobs (used by tests and the CLI)."""
    import app.jobs.handlers  # noqa: F401  (register handlers)

    done: list[Job] = []
    for _ in range(max_jobs):
        db = SessionLocal()
        try:
            if include_delayed:
                db.execute(update(Job).where(Job.status == "pending").values(run_after=utcnow()))
                db.commit()
            job = claim_next(db, "inline")
        finally:
            db.close()
        if job is None:
            break
        done.append(run_job(job.id, "inline"))
    return done
