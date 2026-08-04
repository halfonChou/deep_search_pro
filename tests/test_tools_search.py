from unittest.mock import MagicMock

from app.config import Settings
from app.tools.search_tools import build_search_tools


def test_build_search_tools_returns_list():
    """工厂函数应返回非空工具列表。"""
    settings = MagicMock(spec=Settings)
    settings.tavily_api_key = "fake-key"

    tools = build_search_tools(settings)

    assert isinstance(tools, list)
    assert len(tools) > 0


def test_tool_has_correct_name():
    """返回的工具应该叫 internet_search。"""
    settings = MagicMock(spec=Settings)
    settings.tavily_api_key = "fake-key"

    tools = build_search_tools(settings)

    assert tools[0].name == "internet_search"
