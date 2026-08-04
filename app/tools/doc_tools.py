from pathlib import Path

from langchain_core.tools import tool

from app.infra.path import resolve_in_session


def build_doc_tools(session_dir:Path):
    @tool
    async def generate_markdown(
            content: str,
            filename:str
    ):
        """
        根据文本内容，生成markdown文件
        """
        if not filename.endswith(".md"):
            filename += ".md"

        safe_path = resolve_in_session(filename, session_dir)
        safe_path.parent.mkdir(parents=True, exist_ok=True)

        safe_path.write_text(content, encoding="utf-8")
        return f"markdown 文件'{safe_path}' 成功生成"
    return [generate_markdown]
