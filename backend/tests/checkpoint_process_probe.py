"""Invoked by the process-restart test; only the dedicated test checkpoint DB is used."""

import asyncio
import sys
from typing import TypedDict

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from reimbursement.config import settings


class State(TypedDict):
    answer: str
    completed_steps: int


async def run():
    def ask(state):
        return {"answer": interrupt({"question": "确认"}), "completed_steps": state["completed_steps"] + 1}

    builder = StateGraph(State)
    builder.add_node("ask", ask)
    builder.add_edge(START, "ask")
    builder.add_edge("ask", END)
    config = {"configurable": {"thread_id": sys.argv[1]}}
    async with AsyncPostgresSaver.from_conn_string(settings().checkpoint_url) as saver:
        graph = builder.compile(checkpointer=saver)
        phase = sys.argv[2]
        value = (
            {"answer": "", "completed_steps": 0}
            if phase == "start"
            else (Command(resume="confirmed") if phase == "resume" else None)
        )
        result = await graph.ainvoke(value, config)
        if phase == "start":
            assert result["__interrupt__"]
        else:
            assert result["answer"] == "confirmed" and result["completed_steps"] == 1


if __name__ == "__main__":
    asyncio.run(run())
