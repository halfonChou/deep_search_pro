# app/tools/doc_tools.py
from typing import TYPE_CHECKING

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from app.infra.path import resolve_in_session

if TYPE_CHECKING:                      # ★★ 只在类型检查时导入，运行时不执行
    from app.agents.context import RunContext


def build_doc_tools() -> list:
    """构建交付物工具。★★ 注意：不再接收 session_dir 参数。

    原因：session_dir 是【每次会话】才确定的（在 RunContext 里），
    而这个工厂在应用启动时只跑一次，那时没有任何会话存在。
    解决办法是让工具在【运行时】自己去 ToolRuntime 里取。
    """

    @tool
    async def generate_markdown(
        content: str,
        filename: str,
        runtime: ToolRuntime,          # ★★ 参数名必须叫 runtime，类型必须是 ToolRuntime
    ) -> str:
        """把最终报告写成 markdown 文件，交付给用户下载。

        只有最终要交付给用户的报告才用这个工具。
        中间草稿请用 write_file 写到 /scratch/ 下。
        """
        # ★★ runtime.context 就是你传给 create_deep_agent 的 context_schema=RunContext 的实例。
        # 框架在每次工具调用时自动注入，你什么都不用传。
        ctx: "RunContext" = runtime.context

        if not filename.endswith(".md"):
            filename += ".md"

        safe_path = resolve_in_session(filename, ctx.session_dir)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_text(content, encoding="utf-8")

        # ★★ 只回文件名不回全路径：主 prompt 里写了"不允许发送文档路径给用户"，
        # 从工具返回值这一层就掐掉，比只靠 prompt 约束更可靠。
        return f"报告《{filename}》已生成，用户可在会话目录下载。"

    return [generate_markdown]