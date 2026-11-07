"""Synthetic documents. Matching is by registered content, never by user filenames."""

import hashlib
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

COMPANY_A = "青禾科技有限公司"
COMPANY_B = "青禾供应链有限公司"


@lru_cache
def documents() -> dict:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    common = {"business_date": today, "date_type": "transaction", "execution_mode": "fixture"}
    examples: dict[str, tuple[str, str, dict]] = {
        "payment_meal": (
            "餐饮付款 · 88元",
            "payment",
            {
                **common,
                "document_role": "payment",
                "amount": "88.00",
                "payment_status": "paid",
                "transaction_id": "SYN-PAY-001",
                "expense_type": "餐饮",
                "merchant": "青禾餐厅",
                "observations": [{"type": "paid", "amount": "88.00", "text": "Payment successful CNY 88.00"}],
            },
        ),
        "invoice_meal": (
            "餐饮发票 · 88元",
            "invoice",
            {
                **common,
                "date_type": "invoice_issue",
                "document_role": "tax_invoice",
                "amount": "88.00",
                "buyer_name": COMPANY_A,
                "buyer_tax_number": "SYNTHETIC-BUYER-001",
                "seller_name": "青禾餐厅",
                "seller_tax_number": "SYNTHETIC-SELLER-001",
                "invoice_number": "SYN-INV-001",
                "invoice_type": "电子普票",
                "invoice_date": today,
                "item_name": "餐饮服务",
                "net_amount": "83.02",
                "tax_amount": "4.98",
                "expense_type": "餐饮",
                "observations": [{"type": "total", "amount": "88.00", "text": "Total CNY 88.00"}],
            },
        ),
        "payment_refund": (
            "车票支付 · 含部分退款",
            "payment",
            {
                **common,
                "document_role": "payment",
                "amount": "154.00",
                "refund_amount": "10.50",
                "refund_linked": True,
                "refund_status": "completed",
                "payment_status": "paid",
                "transaction_id": "SYN-RAIL-001",
                "expense_type": "差旅",
                "observations": [
                    {"type": "paid", "amount": "154.00", "text": "Paid CNY 154.00"},
                    {
                        "type": "refunded",
                        "amount": "10.50",
                        "text": "Refund completed CNY 10.50, order SYN-RAIL-001",
                    },
                ],
            },
        ),
        "rail_ticket": (
            "铁路电子客票 · 141元",
            "invoice",
            {
                **common,
                "date_type": "ride",
                "document_role": "title_exempt_transport_receipt",
                "amount": "141.00",
                "invoice_number": "SYN-RAIL-INV-001",
                "buyer_name": "陈晓",
                "invoice_type": "电子普票",
                "invoice_date": today,
                "item_name": "铁路电子客票",
                "expense_type": "差旅",
                "observations": [{"type": "fare", "amount": "141.00", "text": "Rail ticket fare CNY 141.00"}],
            },
        ),
        "order_unpaid": (
            "待付款订单 · 不计实付",
            "payment",
            {
                **common,
                "document_role": "payment",
                "amount": "120.00",
                "payment_status": "unpaid",
                "expense_type": "办公",
                "observations": [{"type": "order", "amount": "120.00", "text": "Awaiting payment"}],
            },
        ),
        "transfer_ambiguous": (
            "聊天转账 · 金额需确认",
            "payment",
            {
                **common,
                "document_role": "unknown",
                "amount": None,
                "payment_status": "unknown",
                "candidates": ["98.00", "198.00"],
                "expense_type": "其他",
                "observations": [
                    {"type": "candidate", "amount": "98.00", "text": "Two transfers; relationship unclear"}
                ],
            },
        ),
        "invoice_wrong_company": (
            "另一公司抬头 · 88元",
            "invoice",
            {
                **common,
                "date_type": "invoice_issue",
                "document_role": "tax_invoice",
                "amount": "88.00",
                "buyer_name": COMPANY_B,
                "buyer_tax_number": "SYNTHETIC-BUYER-002",
                "seller_name": "青禾餐厅",
                "seller_tax_number": "SYNTHETIC-SELLER-001",
                "invoice_number": "SYN-INV-002",
                "invoice_type": "电子普票",
                "invoice_date": today,
                "item_name": "餐饮服务",
                "net_amount": "83.02",
                "tax_amount": "4.98",
                "expense_type": "餐饮",
                "observations": [{"type": "total", "amount": "88.00", "text": "Buyer: Synthetic company B"}],
            },
        ),
        "itinerary": (
            "行程单 · 仅作佐证",
            "other",
            {
                **common,
                "date_type": "ride",
                "document_role": "supporting_document",
                "amount": "141.00",
                "expense_type": "差旅",
                "observations": [
                    {"type": "support", "amount": "141.00", "text": "Itinerary only, not an invoice"}
                ],
            },
        ),
        "payment_multi": (
            "多笔自动扣款 · 48.90元",
            "payment",
            {
                **common,
                "document_role": "payment",
                "amount": "48.90",
                "payment_status": "paid",
                "expense_type": "打车",
                "transactions": [
                    {"id": "SYN-TAXI-A", "amount": "20.00"},
                    {"id": "SYN-TAXI-B", "amount": "28.90"},
                ],
                "observations": [
                    {"type": "paid", "amount": "20.00", "text": "Automatic deduction successful"},
                    {"type": "paid", "amount": "28.90", "text": "Automatic deduction successful"},
                ],
            },
        ),
        "discounted": (
            "优惠付款 · 实付80元",
            "payment",
            {
                **common,
                "document_role": "payment",
                "amount": "80.00",
                "payment_status": "paid",
                "transaction_id": "SYN-DISCOUNT-001",
                "expense_type": "办公",
                "observations": [
                    {"type": "order", "amount": "100.00", "text": "Order CNY 100"},
                    {"type": "discount", "amount": "20.00", "text": "Discount CNY 20"},
                    {"type": "paid", "amount": "80.00", "text": "Paid CNY 80.00"},
                ],
            },
        ),
    }
    result = {}
    for key, (name, kind, facts) in examples.items():
        image = Image.new("RGB", (850, 1000), "#f8f9fb")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((42, 42, 808, 958), radius=18, fill="white", outline="#d6dce7", width=2)
        font_paths = [
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        ]
        font_path = next((p for p in font_paths if p.is_file()), None)
        font = ImageFont.truetype(str(font_path), 27) if font_path else ImageFont.load_default(size=27)
        small = ImageFont.truetype(str(font_path), 21) if font_path else ImageFont.load_default(size=21)
        role = facts["document_role"]
        title = {
            "tax_invoice": "增值税电子普通发票（合成）",
            "title_exempt_transport_receipt": "铁路电子客票（合成）",
            "supporting_document": "行程单（合成 / 非发票）",
            "unknown": "聊天转账记录（合成）",
        }.get(role, "支付详情（合成）")
        draw.text((80, 90), title, font=font, fill="#263351")
        draw.text((80, 145), "SYNTHETIC / Not a real financial document", font=small, fill="#8792a7")
        draw.line((80, 195, 770, 195), fill="#d6dce7", width=2)
        date_label = {"invoice_issue": "开票日期", "ride": "乘车日期", "transaction": "交易日期"}.get(
            facts.get("date_type") or "unknown", "日期"
        )
        values = [f"{date_label}: {today}"]
        if role == "unknown":
            values += ["转账 A: CNY 98.00", "转账 B: CNY 198.00", "两笔转账与本次费用的关系尚未说明"]
        elif role in {"tax_invoice", "title_exempt_transport_receipt"}:
            values += [f"票号: {facts['invoice_number']}", f"购买方: {facts['buyer_name']}"]
            if facts.get("buyer_tax_number"):
                values += [f"购方税号: {facts['buyer_tax_number']}"]
            if facts.get("seller_name"):
                values += [f"销售方: {facts['seller_name']}", f"销方税号: {facts['seller_tax_number']}"]
            values += [f"项目: {facts['item_name']}"]
            if facts.get("net_amount"):
                values += [f"不含税金额: CNY {facts['net_amount']}", f"税额: CNY {facts['tax_amount']}"]
            values += [f"价税合计 / 票价: CNY {facts['amount']}"]
        elif role == "supporting_document":
            values += [f"行程费用: CNY {facts['amount']}", "本行程单仅作业务佐证，不是付款凭证或发票"]
        else:
            values += [
                f"{'原支付金额' if facts.get('refund_amount') else '实付金额' if facts.get('payment_status') == 'paid' else '订单金额'}: CNY {facts['amount']}",
                "付款状态: " + ("支付成功" if facts.get("payment_status") == "paid" else "等待付款"),
            ]
            if facts.get("merchant"):
                values += [f"商户: {facts['merchant']}"]
            if facts.get("transaction_id"):
                values += [f"交易号: {facts['transaction_id']}"]
            if facts.get("refund_amount"):
                values += [
                    f"已完成退款: CNY {facts['refund_amount']}",
                    f"退款对应原交易号: {facts['transaction_id']}",
                ]
            if key == "discounted":
                values += ["原价: CNY 100.00", "优惠: CNY 20.00"]
            for transaction in facts.get("transactions", []):
                values += [f"扣款成功 {transaction['id']}: CNY {transaction['amount']}"]
        for i, value in enumerate(values):
            draw.text((80, 230 + i * 48), value, font=small, fill="#3b4760")
        draw.text((80, 900), "仅供流程测试 · 禁止真实报销", font=small, fill="#8792a7")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        content = buffer.getvalue()
        result[key] = {
            "key": key,
            "name": name + ".png",
            "kind": kind,
            "facts": facts,
            "content": content,
            "content_hash": hashlib.sha256(content).hexdigest(),
        }
    return result


def registered_facts(content_hash: str) -> dict:
    return next((x["facts"] for x in documents().values() if x["content_hash"] == content_hash), {})
