import subprocess
import sys
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from reimbursement.config import settings
from reimbursement.main import app


def test_health():
    with TestClient(app) as client:
        assert client.get("/api/v1/health/live").json()["status"] == "alive"
        assert client.get("/api/v1/health/ready").json()["status"] == "ready"


async def test_checkpoint_survives_connection_restart():
    class State(TypedDict):
        answer: str

    def ask(state):
        return {"answer": interrupt({"question": "确认"})}

    builder = StateGraph(State)
    builder.add_node("ask", ask)
    builder.add_edge(START, "ask")
    builder.add_edge("ask", END)
    config = {"configurable": {"thread_id": f"test:{uuid4()}"}}
    async with AsyncPostgresSaver.from_conn_string(settings().checkpoint_url) as saver:
        graph = builder.compile(checkpointer=saver)
        result = await graph.ainvoke({"answer": ""}, config)
        assert result["__interrupt__"]
    async with AsyncPostgresSaver.from_conn_string(settings().checkpoint_url) as saver:
        graph = builder.compile(checkpointer=saver)
        result = await graph.ainvoke(Command(resume="已确认"), config)
        assert result["answer"] == "已确认"


def test_checkpoint_survives_process_restart_and_completed_replay():
    thread = f"process-test:{uuid4()}"
    probe = Path(__file__).with_name("checkpoint_process_probe.py")
    for phase in ["start", "resume", "replay"]:
        result = subprocess.run(
            [sys.executable, str(probe), thread, phase], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stderr
