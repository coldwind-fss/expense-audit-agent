from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def money_input(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("金额请使用十进制字符串")
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("金额格式不正确") from error
    if not amount.is_finite() or amount < 0 or amount >= Decimal("10000000000000000"):
        raise ValueError("金额不在有效范围内")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("金额最多保留两位小数")
    return format(amount, ".2f")


MoneyInput = Annotated[str | None, BeforeValidator(money_input)]
Workflow = Literal["daily", "no_invoice", "travel", "project", "supply_chain"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RevisionInput(Input):
    expected_revision: int = Field(ge=1)


class ClaimCreate(Input):
    workflow_key: Workflow = "daily"
    title: str = Field(default="新的报销", max_length=200)
    route_mode: Literal["self", "on_behalf", "admin_originator"] = "self"
    subject_id: str | None = None


class ClaimPatch(RevisionInput):
    title: str | None = Field(default=None, max_length=200)
    workflow_key: Workflow | None = None
    route_mode: Literal["self", "on_behalf", "admin_originator"] | None = None
    subject_id: str | None = None
    department_id: str | None = None
    company_id: str | None = None
    account_id: str | None = None
    total_amount: MoneyInput = None
    total_auto: Literal[False] | None = None
    related_ids: list[str] | None = None
    remark: str | None = Field(default=None, max_length=2000)
    travel_date_remark: str | None = Field(default=None, max_length=500)

    @field_validator(
        "title", "workflow_key", "route_mode", "total_auto", "related_ids", "remark", "travel_date_remark"
    )
    @classmethod
    def non_null_fields(cls, value):
        if value is None:
            raise ValueError("该字段不能设置为null")
        return value


class LineInput(RevisionInput):
    business_date: date | None = None
    reason: str = Field(default="", max_length=1000)
    amount: MoneyInput = None
    project: str = ""
    expense_type: str = ""
    invoice_type: str = ""
    related_id: str | None = None
    remark: str = Field(default="", max_length=1000)


class LinePatch(RevisionInput):
    business_date: date | None = None
    reason: str | None = Field(default=None, max_length=1000)
    amount: MoneyInput = None
    project: str | None = None
    expense_type: str | None = None
    invoice_type: str | None = None
    related_id: str | None = None
    remark: str | None = Field(default=None, max_length=1000)


class PersonaInput(Input):
    persona: Literal["employee", "colleague", "admin"]


class AccountInput(Input):
    label: str = Field(min_length=1, max_length=100)
    kind: Literal["bank", "corporate", "alipay", "dingtalk"] = "bank"
    value: str = Field(min_length=4, max_length=500)


class LineView(BaseModel):
    id: str
    business_date: str | None
    reason: str
    amount: str | None
    project: str
    expense_type: str
    invoice_type: str
    related_id: str | None
    remark: str
    sources: dict


class MaterialView(BaseModel):
    id: str
    claim_id: str
    name: str
    media_type: str
    size: int
    kind: str
    line_id: str | None
    status: str
    error: str
    facts: dict
    fact_version: int
    manual_amount: str | None
    duplicate_of: str | None
    duplicate_kind: str
    duplicate_decision: str
    page_count: int


class ClaimView(BaseModel):
    id: str
    revision: int
    title: str
    workflow_key: str
    route_mode: str
    actor_id: str
    subject_id: str
    originator_id: str
    actor_name: str
    subject_name: str
    originator_name: str
    department_id: str
    company_id: str | None
    social_company_id: str | None
    account_id: str | None
    total_amount: str | None
    total_auto: bool
    related_ids: list[str]
    remark: str
    travel_date_remark: str
    status: str
    updated_at: str
    lines: list[LineView]
    materials: list[MaterialView]
    latest_review_id: str | None


class TaskAccepted(BaseModel):
    run_id: str
    task_kind: str
    status: str
    input_revision: int
    execution_mode: str
    poll_after_ms: int = 1000
