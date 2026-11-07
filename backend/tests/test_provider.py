import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.exceptions import ModelRateLimitError, ModelTimeoutError
from langchain_core.messages import AIMessage
from pydantic import SecretStr
from test_workflows import ready_claim

from reimbursement import model_gateway
from reimbursement.agent_graph import Action
from reimbursement.config import settings
from reimbursement.errors import AppError
from reimbursement.model_gateway import ProviderModelGateway


@pytest.mark.parametrize(
    "failure,code",
    [
        (ModelTimeoutError("synthetic"), "MODEL_TIMEOUT"),
        (ModelRateLimitError("synthetic"), "MODEL_RATE_LIMIT"),
        (None, "MODEL_STRUCTURE_INVALID"),
    ],
)
async def test_provider_failures_are_bounded_and_do_not_fallback(monkeypatch, failure, code):
    monkeypatch.setattr(settings(), "model_api_key", SecretStr("synthetic-test-key"))
    request = (
        AsyncMock(side_effect=failure)
        if failure
        else AsyncMock(
            return_value=AIMessage(
                content='{"action":"finish","facts":{"document_role":"payment","amount":"NaN"}}'
            )
        )
    )
    options = []

    class StubModel:
        def __init__(self, **kwargs):
            options.append(kwargs)

        ainvoke = request

    monkeypatch.setattr(model_gateway, "ChatDeepSeek", StubModel)
    gateway = ProviderModelGateway(
        {"provider": "deepseek", "model": "synthetic-vision", "endpoint": "https://api.deepseek.com"}
    )
    with pytest.raises(AppError) as error:
        await gateway.invoke("只返回JSON", Action, {}, {"snapshot": {"claim": {"materials": []}}})
    assert error.value.code == code and "synthetic-test-key" not in error.value.message
    assert request.await_count == 1 and options[0]["max_retries"] == 0


def test_fixture_facts_cannot_be_reused_as_provider_evidence(client, monkeypatch):
    claim = ready_claim(client)
    monkeypatch.setattr(settings(), "model_mode", "provider")
    response = client.post(
        f"/api/v1/claims/{claim['id']}/reviews", json={"expected_revision": claim["revision"]}
    )
    assert response.status_code == 422 and response.json()["error"]["code"] == "FACT_MODE_MISMATCH"


def test_provider_sends_authorized_images_without_fixture_answers(client, monkeypatch):
    claim = ready_claim(client)
    material = claim["materials"][0]
    monkeypatch.setattr(settings(), "model_api_key", SecretStr("synthetic-test-key"))
    seen = []

    class StubModel:
        def __init__(self, **kwargs):
            pass

        async def ainvoke(self, messages, **kwargs):
            seen.extend(messages)
            return AIMessage(
                content=json.dumps(
                    {
                        "action": "finish",
                        "facts": {"document_role": "payment", "amount": "88.00", "payment_status": "paid"},
                    }
                ),
                usage_metadata={"input_tokens": 10, "output_tokens": 12, "total_tokens": 22},
            )

    monkeypatch.setattr(model_gateway, "ChatDeepSeek", StubModel)
    context = {
        "snapshot": {"claim": {"materials": [{"id": material["id"]}]}},
        "observations": {"read_material_pages": {"material_id": material["id"], "pages": [{"page": 1}]}},
    }
    gateway = ProviderModelGateway(
        {"provider": "deepseek", "model": "synthetic-vision", "endpoint": "https://api.deepseek.com"}
    )
    result = asyncio.run(gateway.invoke("只返回JSON", Action, {}, context))
    assert result.facts.amount == "88.00" and gateway.usage["total_tokens"] == 22
    content = seen[1].content
    assert any(isinstance(block, dict) and block.get("type") == "image_url" for block in content)
    assert "fixture_data" not in str(content) and "synthetic-test-key" not in str(content)
