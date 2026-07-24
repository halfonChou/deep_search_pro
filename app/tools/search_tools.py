# from typing import Literal
#
# from langchain_core.tools import tool
# from tavily import TavilyClient
#
# from app.agents.events import  AgentEvent
# from app.config import Settings
# from app.infra.emitter import EventEmitter
#
# def build_search_tools(setting:Settings, emitter:EventEmitter):
#     client = TavilyClient(api_key = Settings.tavily_api_key)
#     @tool
#     async def internet_search(
#             query:str,
#             topic: Literal["news","finance","general"] = "general"
#     )