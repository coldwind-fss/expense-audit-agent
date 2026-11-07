"""Persistent PG jobs; model calls do not hold database transactions."""

import asyncio
import logging
import socket
from datetime import timedelta

from sqlalchemy import or_, select

from .agent_service import publish, worker_context
from .db import SessionLocal, now, uid
from .errors import AppError
from .models import AgentRun, Job, Material, Submission, WorkerHeartbeat
from .observability import configure_logging

logger = logging.getLogger(__name__)


def claim_job(kinds):
    with SessionLocal() as db:
        job = db.scalars(
            select(Job)
            .where(
                Job.kind.in_(kinds),
                Job.available_at <= now(),
                or_(Job.status == "queued", (Job.status == "running") & (Job.lease_until < now())),
            )
            .order_by(Job.available_at, Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).one_or_none()
        if not job:
            return None
        recovered = job.status == "running"
        if recovered and job.kind == "dispatch":
            submission = db.get_one(Submission, job.entity_id)
            submission.status, submission.failure = "unknown", "发送进程中断，请先核对创建结果"
            job.status, job.lease_until = "unknown", None
            db.commit()
            return None
        job.status, job.lease_token, job.lease_until = "running", uid(), now() + timedelta(seconds=45)
        job.attempts += 1
        if job.kind == "agent":
            run = db.get_one(AgentRun, job.entity_id)
            if run.status in {"cancelled", "outdated", "completed"}:
                job.status = "done"
                db.commit()
                return None
            if recovered:
                run.attempt_id = uid()
            run.status = "running"
        result = job.id, job.lease_token
        db.commit()
        return result


async def renew(job_id, token):
    while True:
        await asyncio.sleep(10)
        with SessionLocal() as db:
            job = db.scalars(select(Job).where(Job.id == job_id).with_for_update()).one()
            if not job or job.lease_token != token or job.status != "running":
                return
            job.lease_until = now() + timedelta(seconds=45)
            db.commit()


async def process_job(job_id, token):
    renewal = asyncio.create_task(renew(job_id, token))
    try:
        with SessionLocal() as db:
            job = db.get_one(Job, job_id)
            kind, entity_id, payload = job.kind, job.entity_id, dict(job.payload)
        if kind == "agent":
            from .agent_graph import execute

            output = await execute(entity_id, job_id, token, resume=payload.get("resume"))
            with SessionLocal() as db:
                run = db.get_one(AgentRun, entity_id)
                ctx = worker_context(db, run.workspace_id, payload["actor_id"])
                if "waiting" in output:
                    from .services import load_claim

                    claim = load_claim(db, ctx, run.claim_id, lock=True)
                    job = db.scalars(select(Job).where(Job.id == job_id).with_for_update()).one()
                    db.refresh(run)
                    if job.lease_token == token and run.status == "running":
                        if claim.revision != run.input_revision:
                            run.status, job.status = "outdated", "done"
                        else:
                            run.status, run.question = "waiting_input", output["waiting"]
                            run.output = {"partial_review": output.get("partial_review", {})}
                            job.status, job.lease_until = "waiting", None
                else:
                    publish(db, ctx, run, job_id, token, output)
                db.commit()
        elif kind == "dispatch":
            from .submission_service import dispatch

            await asyncio.to_thread(dispatch, job_id, token)
        elif kind == "ledger":
            from .ledger import process_event

            with SessionLocal() as db:
                job = db.scalars(select(Job).where(Job.id == job_id).with_for_update()).one()
                if job.lease_token == token:
                    if job.payload.get("fault"):
                        raise AppError("SIDECAR_FAILURE", "模拟台账旁路失败；OA创建结果不受影响", 503)
                    process_event(db, entity_id)
                    job.status, job.lease_until = "done", None
                    db.commit()
        elif kind == "import":
            from .imports import process_import

            await asyncio.to_thread(process_import, job_id, token)
        elif kind == "prepare":
            from .preparation import prepare_material

            await asyncio.to_thread(prepare_material, job_id, token)
    except Exception as error:
        message = error.message if isinstance(error, AppError) else "处理失败，请查看任务事件或稍后重试"
        if not isinstance(error, AppError):
            logger.error("job.failed", extra={"job_id": job_id, "error_type": type(error).__name__})
        with SessionLocal() as db:
            job = db.scalars(select(Job).where(Job.id == job_id).with_for_update()).one()
            if job and job.lease_token == token and job.status == "running":
                job.status, job.error, job.lease_until = "failed", message, None
                if job.kind == "agent":
                    run = db.get_one(AgentRun, job.entity_id)
                    if run.status not in {"cancelled", "outdated"}:
                        run.status, run.error, run.finished_at = "failed", message, now()
                        run.stop_reason = error.code if isinstance(error, AppError) else "execution_failed"
                        material = db.get_one(Material, run.material_id) if run.material_id else None
                        if material and material.status != "deleted":
                            material.status, material.error = "failed", message
                elif job.kind == "prepare":
                    material = db.get_one(Material, job.entity_id)
                    if material.status != "deleted":
                        material.status, material.error = "failed", message
                db.commit()
    finally:
        renewal.cancel()
        try:
            await renewal
        except asyncio.CancelledError:
            pass


async def tick(kinds=None):
    claimed = await asyncio.to_thread(
        claim_job, kinds or ["prepare", "agent", "import", "dispatch", "ledger"]
    )
    if claimed:
        await process_job(*claimed)
        return True
    return False


async def lane(kinds):
    while True:
        if not await tick(kinds):
            await asyncio.sleep(1)


async def heartbeat():
    worker_id = f"worker:{socket.gethostname()}"
    while True:
        with SessionLocal() as db:
            beat = db.get(WorkerHeartbeat, worker_id)
            if beat is None:
                beat = WorkerHeartbeat(id=worker_id)
                db.add(beat)
            beat.updated_at = now()
            db.commit()
        await asyncio.sleep(5)


async def main():
    await asyncio.gather(
        heartbeat(),
        lane(["prepare", "agent", "import"]),
        lane(["prepare", "agent"]),
        lane(["dispatch", "ledger"]),
    )


if __name__ == "__main__":
    configure_logging()
    asyncio.run(main())
