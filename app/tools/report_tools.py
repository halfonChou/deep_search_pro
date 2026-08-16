"""历史报告查询工具（Day 10）。

这是 §1.6 里「用拉代替推」的核心实现：
- 记忆是"推"的（每轮自动注入上下文），索引是"拉"的（只在模型调用时才读）。
- 拉的那种没有膨胀风险，成本接近零，且需要时能拿到完整历史。
- 这个工具替代了本来要做的长期记忆（L3），判断依据见 §1.6。

返回值只包含一句话摘要 + 路径，绝不包含报告全文。
"""

from __future__ import annotations

from langchain_core.tools import tool

from app.services.session_service import SessionService


def build_report_tools(sessions: SessionService) -> list:
    @tool
    async def list_past_reports(
        keyword: str | None = None,
    ) -> str:
        """查询以前生成过的分析报告，避免重复调研。

        可选按关键词筛选。返回每份报告的主题、一句话摘要、路径和时间。
        如果你需要查看报告全文，请告知用户到对应路径下载。

        Args:
            keyword: 可选筛选关键词，匹配报告主题或摘要。留空则返回最近的报告。
        """
        reports = await sessions.list_reports(keyword=keyword)

        if not reports:
            if keyword:
                return f"未找到与「{keyword}」相关的历史报告。"
            return "暂无历史报告记录。"

        lines: list[str] = []
        for r in reports:
            topic = r.get("topic", "未知主题")
            summary = r.get("summary", "")
            path = r.get("path", "")
            lines.append(f"- 主题: {topic} | 摘要: {summary} | 路径: {path}")

        return f"找到 {len(reports)} 份历史报告：\n" + "\n".join(lines)

    return [list_past_reports]
