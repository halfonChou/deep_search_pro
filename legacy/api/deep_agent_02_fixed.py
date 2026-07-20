from langchain.tools import tool # 封装工具装饰器
from typing import Literal # 指定查询网络信息的类型
from tavily import TavilyClient #网络搜索工具
from dotenv import load_dotenv,find_dotenv
import os # 加载配置文件
from langchain.chat_models import init_chat_model
from deepagents import create_deep_agent

# 加载配置
load_dotenv(find_dotenv())
llm_name = os.getenv('LLM_MODEL')
tavily_api_key = os.getenv('TAVILY_API_KEY')

# 1-准备网络搜索工具


# 初始化网络工具客户端
tavily_client = TavilyClient(api_key=tavily_api_key)

@tool
def internet_search(
        query: str, #搜索内容
        max_results: int = 5,
        topic: Literal['news', 'finance', 'general'] = 'general',
        include_raw_content: bool = True, # false精简搜索
):
    """
    :param query: 搜索关键字
    :param max_results:返回条数
    :param topic:新闻类型
    :param include_raw_content: 是否精简 false 精简 否则详细
    :return:查询结果
    """
    print(f"开始网络工具调用！核心参数：{query},{max_results},{topic},{include_raw_content}")
    return tavily_client.search(
        query=query,
        max_results=max_results,
        topic=topic,
        include_raw_content=include_raw_content,
    )


# 2-初始化模型对象

llm = init_chat_model(
    model=llm_name,
    model_provider='openai'
)

# 3-创建深度智能体
deep_agent = create_deep_agent(
    model=llm,
    tools=[internet_search],
    subagents=[],
    system_prompt=f"""
    你是一个专家级的研究员，你有权使用：internet_search工具来收集信息，
    最终，你要更具工具生成一个精美的报告
    """
)

# 4-1 流式

stream = deep_agent.stream(
    {
        "messages": [
            {"role": "user", "content": "查询2026年7月和光模块，算力有关的热门金融股市信息"},
        ]
    }
)

# 循环得到结果
for chunk in stream:
    for node_name, state in chunk.items():
        if not state or "messages" not in state:
            continue
        messages = state["messages"]
        if messages and isinstance(messages, list):
            last = messages[-1]
            if node_name == "model":
                if last.tool_calls:
                    for tool_call in last.tool_calls:
                        if tool_call["name"] == "task":
                            print(f"调用子智能体:{tool_call['args']['subagent_type']}")
                        else:
                            print(f"调用工具:{tool_call['name']}，参数{tool_call['args']}")
                elif last.content:
                    print(f"大模型的最终回答{last.content}")
            elif node_name == "tools":
                tool_return_result = last.content
                tool_name = last.name
                print(f"agent调用了{tool_name}工具，返回{tool_return_result}")
