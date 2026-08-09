from langchain_core.tools import tool

from app.rag.retriever import Retriever


def build_rag_tools(retriever: Retriever) -> list:
    @tool
    async def rag_search(query: str) -> str:
        """在企业知识库中检索与查询相关的文档片段。

        适用场景：药品存储规范、使用说明、安全须知等企业内部文档查询。
        返回匹配的文档片段及来源信息，如无匹配则明确说明。

        """
        hits = await retriever.search(query)

        if not hits:
            return f"知识库中未找到与「{query}」相关的内容。建议改用网络搜索获取公开资料。"


        parts: list[str] = []
        for i, hit in enumerate(hits, start=1):
            source = hit.metadata.get("source", "未知来源")
            parts.append(
                f"【片段 {i}】(来源: {source}, 相关度: {hit.score:.2f})\n"
                f"{hit.text}"
            )

        return "\n\n---\n\n".join(parts)

    return [rag_search]