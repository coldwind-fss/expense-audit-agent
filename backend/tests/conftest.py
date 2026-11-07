"""All new integration tests use the isolated *_test database, never legacy data."""

import os

os.environ["MODEL_MODE"] = "fixture"
os.environ["MODEL_API_KEY"] = ""

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://reimbursement:development@127.0.0.1:15432/reimbursement_v2_test"
)
os.environ.setdefault(
    "CHECKPOINT_URL",
    "postgresql://reimbursement:development@127.0.0.1:15432/reimbursement_v2_test?options=-csearch_path%3Dagent_runtime",
)
os.environ.setdefault("FILE_ROOT", "../data/v2/test-files")
if not os.environ["DATABASE_URL"].endswith("/reimbursement_v2_test"):
    raise RuntimeError("Tests require the dedicated reimbursement_v2_test database")

import pytest
from fastapi.testclient import TestClient

from reimbursement.main import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        result = client.post("/api/v1/experience/sessions")
        assert result.status_code == 201
        client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
        yield client
