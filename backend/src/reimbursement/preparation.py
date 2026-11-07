from sqlalchemy import select

from .agent_service import start_run, worker_context
from .api_materials import file_path, prepare_bytes
from .db import SessionLocal
from .models import Job, Material
from .services import audit, load_claim


def prepare_material(job_id, token):
    with SessionLocal() as db:
        job = db.get_one(Job, job_id)
        material = db.get_one(Material, job.entity_id)
        content, media_type = file_path(material.storage_key).read_bytes(), material.media_type
    pages = prepare_bytes(content, media_type)
    with SessionLocal() as db:
        initial = db.get_one(Job, job_id)
        ctx = worker_context(db, initial.workspace_id, initial.payload["actor_id"])
        claim = load_claim(db, ctx, initial.payload["claim_id"], lock=True)
        job = db.scalars(select(Job).where(Job.id == job_id).with_for_update()).one()
        if job.lease_token != token or job.status != "running":
            return
        material = db.get_one(Material, job.entity_id)
        if material.status == "deleted" or claim.status != "draft":
            job.status = "done"
        else:
            keys = []
            for index, content in enumerate(pages):
                key = f"{ctx.workspace_id}/{material.id}/page-{index + 1}.png"
                file_path(key).write_bytes(content)
                keys.append(key)
            material.pages, material.status, material.error = keys, "ready_for_extraction", ""
            start_run(db, ctx, claim, "material_extract", material)
            job.status = "done"
            audit(db, ctx, "material.prepared", claim.id, material_id=material.id, pages=len(keys))
        job.lease_until = None
        db.commit()
