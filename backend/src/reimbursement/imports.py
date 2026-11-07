from io import BytesIO

from openpyxl import load_workbook
from sqlalchemy import select

from .agent_service import worker_context
from .api_materials import file_path, store_material
from .db import SessionLocal
from .errors import AppError
from .models import ClaimLine, Job, Material
from .services import bump_claim, check_revision, load_claim


def import_rows(db, context, claim, content):
    import zipfile

    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            if sum(x.file_size for x in archive.infolist()) > 200_000_000:
                raise AppError("FILE_TOO_LARGE", "导入文件展开后过大", 413)
        workbook = load_workbook(BytesIO(content), data_only=True)
    except (zipfile.BadZipFile, ValueError, OSError) as error:
        raise AppError("UNSUPPORTED_MEDIA_TYPE", "请使用.xlsx格式的日常费用模板", 415) from error
    sheet = workbook.active
    headers = {str(cell.value or "").strip(): cell.column for cell in sheet[1]}
    required = {"申请事由", "金额", "付款截图", "发票"}
    if not required.issubset(headers):
        raise AppError(
            "VALIDATION_ERROR", "模板第一行需含申请事由、金额、付款截图、发票；支持费用日期、所属项目", 422
        )
    images: dict[tuple[int, int], list] = {}
    for image in sheet._images:
        anchor = image.anchor._from
        images.setdefault((anchor.row + 1, anchor.col + 1), []).append(image)
    result = []
    for row in list(sheet.iter_rows(min_row=2, max_row=min(sheet.max_row, 201))):
        number = row[0].row

        def val(header):
            return sheet.cell(number, headers[header]).value if header in headers else None

        payments = images.get((number, headers["付款截图"]), [])
        invoices = images.get((number, headers["发票"]), [])
        if not val("申请事由") or not val("金额") or not payments or not invoices:
            result.append(
                {"row": number, "status": "skipped", "reason": "缺少事由、金额或嵌入的付款/发票图片"}
            )
            continue
        from datetime import date, datetime

        from .schemas import money_input

        date_value = val("费用日期")
        line = ClaimLine(
            workspace_id=context.workspace_id,
            claim_id=claim.id,
            position=number,
            reason=str(val("申请事由")),
            amount=money_input(str(val("金额"))),
            business_date=date_value.date()
            if isinstance(date_value, datetime)
            else (date.fromisoformat(str(date_value)) if date_value else None),
            project=str(val("所属项目") or ""),
            sources={k: {"kind": "import"} for k in ["reason", "amount", "business_date", "project"]},
        )
        db.add(line)
        db.flush()
        for kind, row_images in [("payment", payments), ("invoice", invoices)]:
            for index, image in enumerate(row_images):
                store_material(
                    db,
                    context,
                    claim,
                    f"导入第{number}行-{kind}-{index + 1}.png",
                    image._data(),
                    "image/png",
                    kind,
                    line.id,
                )
        result.append({"row": number, "status": "imported", "line_id": line.id})
    bump_claim(db, context, claim, "excel.imported")
    return {
        "items": result,
        "revision": claim.revision,
        "imported": sum(r["status"] == "imported" for r in result),
        "unprocessed_rows": max(0, sheet.max_row - 201),
    }


def process_import(job_id, token):
    with SessionLocal() as db:
        initial = db.get_one(Job, job_id)
        context = worker_context(db, initial.workspace_id, initial.payload["actor_id"])
        claim = load_claim(db, context, initial.payload["claim_id"], edit=True, lock=True)
        job = db.scalars(select(Job).where(Job.id == job_id).with_for_update()).one()
        if job.lease_token != token or job.status != "running":
            return
        check_revision(claim, job.payload["input_revision"])
        material = db.get_one(Material, job.entity_id)
        result = import_rows(db, context, claim, file_path(material.storage_key).read_bytes())
        job.status, job.lease_until = "done", None
        job.payload = {**job.payload, "result": result}
        db.commit()
