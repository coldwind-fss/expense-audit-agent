"""One executor, with explicit task inputs, instructions, tools and budgets."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskHandler:
    prompt: str
    tools: frozenset[str]
    model_limit: int
    tool_limit: int
    timeout_seconds: int


HANDLERS = {
    "material_extract": TaskHandler(
        "读取当前单份材料。区分角色、原价/实付/退款和日期类型，保留证据及未知。不得按文件名猜金额，不分配或创建费用行。",
        frozenset({"read_material_pages"}),
        4,
        8,
        180,
    ),
    "line_suggest": TaskHandler(
        "仅基于员工已分配材料提出金额、费用日期、票种/类型建议。保护人工字段，不写实际用途，不增删费用行。",
        frozenset({"read_cached_facts", "calculate_supported_amounts"}),
        2,
        4,
        60,
    ),
    "claim_review": TaskHandler(
        "对当前版本申报执行必要业务检查，可用白名单工具补看证据。金额由工具计算，缺证据提出具体问题，不反复求通过。",
        frozenset({"read_cached_facts", "read_material_pages", "run_rule_checks"}),
        6,
        12,
        180,
    ),
}
