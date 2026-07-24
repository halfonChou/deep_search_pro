from pathlib import Path

from langchain_core.tools import tool

from app.agents.events import AgentEvent
from app.infra.emitter import EventEmitter
from app.infra.path import resolve_in_session


def build_doc_tools(session_dir:Path, emitter:EventEmitter):
    @tool
    async def generate_markdown(
            content: str,
            filename:str
    ):
        """
        根据文本内容，生成markdown文件
        """
        if filename.endswith(".md"):
            filename += ".md"

        safe_path = resolve_in_session(filename, session_dir)
        safe_path.parent.mkdir(parents=True, exist_ok=True)

        await emitter.emit(
            AgentEvent(
                type="tool_start",
                thread_id="",
                message="markdown 文档生成工具",
                data={"filename":filename}
            )
        )
        safe_path.write_text(content, encoding="utf-8")
        return f"markdown 文件'{safe_path}' 成功生成"
    return [generate_markdown]
