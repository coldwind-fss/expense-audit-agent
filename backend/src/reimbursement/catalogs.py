WORKFLOWS = [
    {
        "key": "daily",
        "label": "日常报销 · 有票",
        "description": "餐饮、办公、采购等日常支出",
        "icon": "Receipt",
        "requires_invoice": True,
    },
    {
        "key": "no_invoice",
        "label": "日常报销 · 无票",
        "description": "有真实支出，暂无法取得发票",
        "icon": "Document",
        "requires_invoice": False,
    },
    {
        "key": "travel",
        "label": "出差差旅",
        "description": "关联出差申请的交通、住宿费用",
        "icon": "Suitcase",
        "requires_invoice": True,
    },
    {
        "key": "project",
        "label": "项目制报销",
        "description": "同一项目下的多项费用",
        "icon": "FolderOpened",
        "requires_invoice": True,
    },
    {
        "key": "supply_chain",
        "label": "采购供应链",
        "description": "授权账号的发票专属报销",
        "icon": "Box",
        "requires_invoice": True,
    },
]
PROJECTS = ["日常运营", "产品研发", "市场活动", "客户服务"]
EXPENSE_TYPES = ["餐饮", "打车", "办公", "差旅", "住宿", "其他", "员工借款", "对公打款", "其他支出"]
INVOICE_TYPES = ["电子普票", "电子专票", "纸质普通", "纸质专票", "无"]


def canonical_invoice_type(value: str, role: str) -> str:
    if role == "title_exempt_transport_receipt":
        return "电子普票"
    value = value.removesuffix("（合成）").strip()
    aliases = {
        "增值税电子普通发票": "电子普票",
        "电子普通发票": "电子普票",
        "增值税电子专用发票": "电子专票",
        "电子专用发票": "电子专票",
    }
    result = aliases.get(value, value)
    return result if result in INVOICE_TYPES else ""


DIFFICULTIES = ["rules", "steps", "hints", "recognition", "smooth", "other"]
PRIORITIES = ["uploads", "details", "company_account", "approvals", "validation", "none", "other"]
