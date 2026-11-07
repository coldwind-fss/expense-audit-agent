import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from .config import settings


async def init_checkpoints():
    async with AsyncPostgresSaver.from_conn_string(settings().checkpoint_url) as saver:
        await saver.setup()


if __name__ == "__main__":
    asyncio.run(init_checkpoints())
