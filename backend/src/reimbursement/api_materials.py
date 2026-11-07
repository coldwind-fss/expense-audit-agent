import hashlib
from io import BytesIO
from pathlib import Path
from typing import Literal

import pypdfium2 as pdfium
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, now, uid
from .errors import AppError
from .fixtures import documents, registered_facts
from .models import ClaimLine, HumanDecision, Job, Material
from .schemas import ClaimView, Input, MaterialView, MoneyInput, RevisionInput
from .security import Context, current_context
from .services import bump_claim, check_revision, claim_view, load_claim, material_view, scoped

router = APIRouter(prefix="/api/v1")


class Binding(Input):
    material_id: str
    line_id: str | None
    kind: Literal["payment", "invoice", "other"]


class BindingsInput(RevisionInput):
    bindings: list[Binding]


class MaterialDecision(RevisionInput):
    manual_amount: MoneyInput = None
    duplicate_decision: Literal["same", "different", ""] | None = None


class RenameInput(Input):
    name: str = Field(min_length=1, max_length=250)


def file_path(storage_key: str) -> Path:
    root = settings().file_root.resolve()
    candidate = (root / storage_key).resolve()
    if not candidate.is_relative_to(root):
        raise AppError("FORBIDDEN", "文件路径不可用", 403)
    return candidate


def prepare_bytes(content: bytes, media_type: str) -> list[bytes]:
    if media_type == "application/pdf":
        try:
            pdf = pdfium.PdfDocument(content)
            if len(pdf) > 20:
                raise AppError("CAPACITY_LIMIT", "单份PDF最多20页，请按需要拆分后上传", 413)
            pages = []
            for page in pdf:
                image = page.render(scale=1.5).to_pil()
                image.thumbnail((2000, 2600))
                out = BytesIO()
                image.save(out, "PNG")
                pages.append(out.getvalue())
            return pages
        except (pdfium.PdfiumError, ValueError) as error:
            raise AppError("UNSUPPORTED_MEDIA_TYPE", "无法读取这份PDF，请核对文件", 415) from error
    if media_type.startswith("image/"):
        try:
            with Image.open(BytesIO(content)) as image:
                if image.width * image.height > 40_000_000:
                    raise AppError("CAPACITY_LIMIT", "图片尺寸过大，请缩小后上传", 413)
                image = image.convert("RGB")
                image.thumbnail((2000, 2600))
                out = BytesIO()
                image.save(out, "PNG")
                return [out.getvalue()]
        except (UnidentifiedImageError, OSError) as error:
            raise AppError("UNSUPPORTED_MEDIA_TYPE", "无法读取图片，请核对文件格式", 415) from error
    return []


def store_material(
    db: Session,
    context: Context,
    claim,
    name: str,
    content: bytes,
    media_type: str,
    kind: str,
    target_line_id: str | None = None,
) -> tuple[Material, bool]:
    if not content or len(content) > 50_000_000:
        raise AppError("FILE_TOO_LARGE", "文件为空或超过50MB", 413)
    content_hash = hashlib.sha256(content).hexdigest()
    existing = db.scalar(
        select(Material).where(
            Material.claim_id == claim.id, Material.content_hash == content_hash, Material.status != "deleted"
        )
    )
    if existing:
        return existing, True
    current = db.scalars(select(Material).where(Material.workspace_id == context.workspace_id)).all()
    if len(current) >= 50 or sum(m.size for m in current) + len(content) > 200_000_000:
        raise AppError("CAPACITY_LIMIT", "当前体验空间最多50份、合计200MB材料", 429)
    allowed = {"image/png", "image/jpeg", "image/webp", "application/pdf"}
    offices = {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    if media_type not in allowed and not (kind == "other" and media_type in offices):
        raise AppError("UNSUPPORTED_MEDIA_TYPE", "请上传PNG、JPG、WebP或PDF；Office文件仅作为其他附件", 415)
    line = None
    if target_line_id:
        line = db.scalar(
            select(ClaimLine).where(ClaimLine.id == target_line_id, ClaimLine.claim_id == claim.id)
        )
    identifier = uid()
    storage_key = f"{context.workspace_id}/{identifier}/original"
    path = file_path(storage_key)
    if media_type in allowed:
        try:
            if media_type == "application/pdf":
                with pdfium.PdfDocument(content) as pdf:
                    if len(pdf) > 20:
                        raise AppError("CAPACITY_LIMIT", "单份PDF最多20页", 413)
            else:
                with Image.open(BytesIO(content)) as image:
                    if image.width * image.height > 40_000_000:
                        raise AppError("CAPACITY_LIMIT", "图片尺寸过大，请缩小后上传", 413)
                    image.verify()
        except (pdfium.PdfiumError, ValueError, UnidentifiedImageError, OSError) as error:
            raise AppError("UNSUPPORTED_MEDIA_TYPE", "文件内容与图片/PDF格式不符", 415) from error
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    material = Material(
        id=identifier,
        workspace_id=context.workspace_id,
        claim_id=claim.id,
        name=Path(name).name[:250],
        content_hash=content_hash,
        storage_key=storage_key,
        media_type=media_type,
        size=len(content),
        kind=kind,
        line_id=line.id if line else None,
        pages=[],
        fixture_data=registered_facts(content_hash),
        status="uploaded" if media_type in allowed else "stored",
    )
    db.add(material)
    db.flush()
    if media_type in allowed:
        db.add(
            Job(
                workspace_id=context.workspace_id,
                kind="prepare",
                entity_id=material.id,
                payload={"actor_id": context.actor.id, "claim_id": claim.id},
            )
        )
    return material, False


@router.get("/sample-materials")
def samples(context: Context = Depends(current_context)):
    return {
        "items": [
            {
                "key": d["key"],
                "name": d["name"],
                "kind": d["kind"],
                "description": "合成业务材料 · 固定样本识别",
                "url": f"/api/v1/sample-materials/{d['key']}",
            }
            for d in documents().values()
        ],
        "mode": "fixture",
    }


@router.get("/sample-materials/{sample_key}")
def download_sample(sample_key: str, context: Context = Depends(current_context)):
    item = documents().get(sample_key)
    if not item:
        raise AppError("RESOURCE_NOT_FOUND", "样本不存在", 404)
    return Response(content=item["content"], media_type="image/png")


@router.get("/sample-material-manifest")
def sample_manifest(context: Context = Depends(current_context)):
    return {
        "fixture_version": "synthetic.v1",
        "execution_mode": "fixture",
        "items": [
            {
                "key": item["key"],
                "content_hash": item["content_hash"],
                "expected_facts": item["facts"],
                "kind": item["kind"],
                "human_step": "人工分配至真实费用明细；未知金额由人工确认",
            }
            for item in documents().values()
        ],
    }


@router.post("/claims/{claim_id}/materials", response_model=MaterialView, status_code=201)
def upload_material(
    claim_id: str,
    file: UploadFile = File(),
    kind: Literal["payment", "invoice", "other"] = Form("payment"),
    target_line_id: str | None = Form(None),
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    claim = load_claim(db, context, claim_id, edit=True, lock=True)
    content = file.file.read(50_000_001)
    material, duplicate = store_material(
        db,
        context,
        claim,
        file.filename or "附件",
        content,
        file.content_type or "application/octet-stream",
        kind,
        target_line_id,
    )
    if not duplicate:
        bump_claim(db, context, claim, "material.uploaded")
    db.commit()
    return material_view(material)


@router.get("/materials/{material_id}", response_model=MaterialView)
def get_material(
    material_id: str, context: Context = Depends(current_context), db: Session = Depends(get_db)
):
    material = scoped(db, Material, material_id, context.workspace_id)
    load_claim(db, context, material.claim_id)
    return material_view(material)


@router.post("/materials/{material_id}/prepare", status_code=202)
def retry_prepare(
    material_id: str,
    body: RevisionInput,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    material = scoped(db, Material, material_id, context.workspace_id)
    claim = load_claim(db, context, material.claim_id, edit=True, lock=True)
    check_revision(claim, body.expected_revision)
    if material.status != "failed" or material.pages:
        raise AppError("INVALID_STATE", "仅原件准备失败可在此重试", 409)
    job = db.scalars(
        select(Job).where(Job.kind == "prepare", Job.entity_id == material.id).with_for_update()
    ).one()
    job.status, job.error, job.available_at = "queued", "", now()
    material.status, material.error = "uploaded", ""
    db.commit()
    return {"job_id": job.id, "status": job.status}


@router.get("/materials/{material_id}/preview")
def preview(
    material_id: str,
    page: int | None = None,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    material = scoped(db, Material, material_id, context.workspace_id)
    load_claim(db, context, material.claim_id)
    key = material.storage_key
    content_type = material.media_type
    if page is not None:
        if page < 1 or page > len(material.pages):
            raise AppError("RESOURCE_NOT_FOUND", "附件页不存在", 404)
        key, content_type = material.pages[page - 1], "image/png"
    path = file_path(key)
    if not path.exists():
        raise AppError("RESOURCE_NOT_FOUND", "原件暂不可读，请重新上传", 404)
    from fastapi.responses import FileResponse

    return FileResponse(path, media_type=content_type, content_disposition_type="inline")


@router.patch("/materials/{material_id}", response_model=MaterialView)
def rename(
    material_id: str,
    body: RenameInput,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    material = scoped(db, Material, material_id, context.workspace_id)
    claim = load_claim(db, context, material.claim_id, edit=True, lock=True)
    material.name = Path(body.name).name
    from .services import audit

    audit(db, context, "material.renamed", claim.id, material_id=material.id)
    db.commit()
    return material_view(material)


@router.delete("/materials/{material_id}", response_model=ClaimView)
def remove(
    material_id: str,
    expected_revision: int,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    material = scoped(db, Material, material_id, context.workspace_id)
    claim = load_claim(db, context, material.claim_id, edit=True, lock=True)
    check_revision(claim, expected_revision)
    material.status = "deleted"
    material.line_id = None
    bump_claim(db, context, claim, "material.removed")
    db.commit()
    return claim_view(db, claim)


@router.put("/claims/{claim_id}/bindings", response_model=ClaimView)
def assign(
    claim_id: str,
    body: BindingsInput,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    claim = load_claim(db, context, claim_id, edit=True, lock=True)
    check_revision(claim, body.expected_revision)
    for binding in body.bindings:
        material = scoped(db, Material, binding.material_id, context.workspace_id)
        if material.claim_id != claim.id:
            raise AppError("RESOURCE_NOT_FOUND", "材料不属于此报销", 404)
        if binding.line_id:
            line = scoped(db, ClaimLine, binding.line_id, context.workspace_id)
            if line.claim_id != claim.id:
                raise AppError("RESOURCE_NOT_FOUND", "目标行不属于此报销", 404)
        material.line_id, material.kind = binding.line_id, binding.kind
    from .rules import sync_line_amounts

    sync_line_amounts(db, claim)
    bump_claim(db, context, claim, "material.bound")
    db.commit()
    return claim_view(db, claim)


@router.post("/materials/{material_id}/decisions", response_model=ClaimView)
def decide(
    material_id: str,
    body: MaterialDecision,
    request: Request,
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    material = scoped(db, Material, material_id, context.workspace_id)
    claim = load_claim(db, context, material.claim_id, edit=True, lock=True)
    check_revision(claim, body.expected_revision)
    if "manual_amount" in body.model_fields_set:
        if material.kind != "payment" or material.facts.get("document_role") not in {"payment", "unknown"}:
            raise AppError("FORBIDDEN", "只有付款或未知付款材料可以人工确认金额，不能手工认证发票", 403)
        if material.facts.get("payment_status") == "unpaid":
            raise AppError("SUBMISSION_BLOCKED", "待付款订单不能人工确认为已付款", 422)
        material.manual_amount = body.manual_amount
    if body.duplicate_decision is not None:
        if material.duplicate_kind == "exact" and body.duplicate_decision == "different":
            raise AppError("SUBMISSION_BLOCKED", "已明确为同一凭证，不能重复计入", 422)
        material.duplicate_decision = body.duplicate_decision
    db.add(
        HumanDecision(
            workspace_id=context.workspace_id,
            claim_id=claim.id,
            material_id=material.id,
            actor_id=context.actor.id,
            decision_type="material_confirmation",
            value=body.model_dump(mode="json", exclude={"expected_revision"}),
        )
    )
    from .rules import sync_line_amounts

    sync_line_amounts(db, claim)
    bump_claim(db, context, claim, "material.confirmed")
    db.commit()
    return claim_view(db, claim)


@router.post("/claims/{claim_id}/imports", status_code=202)
def import_excel(
    claim_id: str,
    file: UploadFile = File(),
    expected_revision: int = Form(),
    context: Context = Depends(current_context),
    db: Session = Depends(get_db),
):
    from .models import Job

    claim = load_claim(db, context, claim_id, edit=True, lock=True)
    check_revision(claim, expected_revision)
    if claim.workflow_key in {"no_invoice", "travel"}:
        raise AppError("INVALID_STATE", "当前入口请按明细填写，暂不使用此日常导入模板", 409)
    material, duplicate = store_material(
        db,
        context,
        claim,
        file.filename or "费用导入.xlsx",
        file.file.read(50_000_001),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "other",
    )
    if duplicate:
        job = db.scalar(select(Job).where(Job.kind == "import", Job.entity_id == material.id))
        if job:
            return {"job_id": job.id, "status": job.status, "poll_after_ms": 1000}
    material.status = "stored"
    bump_claim(db, context, claim, "excel.queued")
    job = Job(
        workspace_id=context.workspace_id,
        kind="import",
        entity_id=material.id,
        payload={"actor_id": context.actor.id, "claim_id": claim.id, "input_revision": claim.revision},
    )
    db.add(job)
    db.flush()
    db.commit()
    return {"job_id": job.id, "status": job.status, "poll_after_ms": 1000}


@router.get("/import-jobs/{job_id}")
def import_job(job_id: str, context: Context = Depends(current_context), db: Session = Depends(get_db)):
    from .models import Job

    job = scoped(db, Job, job_id, context.workspace_id)
    if job.kind != "import":
        raise AppError("RESOURCE_NOT_FOUND", "导入任务不存在", 404)
    load_claim(db, context, job.payload["claim_id"])
    return {"id": job.id, "status": job.status, "error": job.error, "result": job.payload.get("result")}
