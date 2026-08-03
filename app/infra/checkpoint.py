from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite
from app.config import Settings


async def build_checkpoint(settings: Settings):
    settings.checkpoint_db.parent.mkdir(exist_ok=True, parents=True)

    connect = await aiosqlite.connect(str(settings.checkpoint_db))
    await connect.execute("PRAGMA journal_mode=WAL")
    await connect.execute("PRAGMA busy_timeout=5000")

    saver = AsyncSqliteSaver(connect)
    await saver.setup()
    return saver