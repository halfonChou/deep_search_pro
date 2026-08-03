# 第三阶段：用原生LangGraph重构 + 同步写测试（10天）

> **日期：** 7月20日 - 7月30日（跳过7/19、7/26周六）
> **目标：** 去掉 deepagents 依赖，用原生 LangGraph 重写核心编排。每个模块写完同步写 pytest。
> **核心原则：** 写一个模块，测一个模块。

---

## 重构后的目标项目结构

```
deep_search_pro/
├── agent/
│   ├── __init__.py
│   ├── llm.py                    # LLM模型加载（保留，微调）
│   ├── graph.py                  # 【新建】主StateGraph定义 + 编排逻辑
│   ├── state.py                  # 【新建】自定义State类型定义
│   ├── nodes.py                  # 【新建】各节点函数（主Agent节点、路由函数）
│   └── subgraphs/                # 【新建】替代原 subagents/
│       ├── __init__.py
│       ├── network_search.py     # 网络搜索子图
│       ├── database_query.py     # 数据库查询子图
│       └── knowledge_rag.py      # 本地RAG子图（替代ragflow）
├── api/
│   ├── server.py                 # FastAPI服务（保留，重构对接）
│   ├── context.py                # ContextVar（保留）
│   └── monitor.py                # Monitor（保留，适配新流式输出）
├── tools/
│   ├── __init__.py
│   ├── db_tools.py               # 数据库工具（重构：安全加固 + 消除重复）
│   ├── tavily_tool.py            # 网络搜索工具（保留，清理注释）
│   ├── rag_tools.py              # 【新建】本地RAG工具（替代 ragflow_tools.py）
│   ├── markdown_tools.py         # Markdown生成（保留，清理）
│   ├── pdf_tools.py              # PDF转换（保留，清理）
│   └── upload_file_read_tool.py  # 文件读取（保留，清理）
├── knowledge_base/               # 【新建】RAG知识库文档目录
│   ├── 药品使用说明.txt
│   ├── 药品存储规范.txt
│   └── ...（准备3-5份药品相关文档）
├── data/
│   └── chroma_db/                # 【新建】ChromaDB持久化存储（.gitignore）
├── prompt/
│   └── prompts.yml               # Prompt配置（重写）
├── tests/                        # 【新建】测试目录
│   ├── __init__.py
│   ├── conftest.py               # pytest fixtures（mock LLM、mock DB等）
│   ├── test_graph.py             # 主图路由测试
│   ├── test_network_agent.py     # 网络搜索子图测试
│   ├── test_db_agent.py          # 数据库子图 + SQL安全测试
│   ├── test_rag_agent.py         # 本地RAG子图测试
│   └── test_fallback.py          # （第四阶段再写）
├── utils/
│   ├── path_utils.py             # 路径工具（保留，优化）
│   └── word_converter.py         # Word转换（保留）
├── .env                          # 环境变量
├── .gitignore                    # 【新建】
├── requirements.txt              # 清理更新
└── README.md                     # （第六阶段写）
```

**删除的文件/目录：**
- `agent/subagents/`（整个目录，被 `agent/subgraphs/` 替代）
- `agent/prompts.py`（逻辑合并到 `agent/graph.py` 中直接加载）
- `tools/ragflow_tools.py`（被 `tools/rag_tools.py` 替代）
- `rawflow/`（整个目录，不再需要）
- `api/1.py`、`api/deep_agent_02_fixed.py`（历史遗留文件）
- 所有 `__pycache__/` 目录
- 所有学习笔记文件（`学习笔记.md`、`server_学习笔记.md`、`help.md`、`项目搭建与运行指南.md`、`项目步骤`）

---

## Day 10 — 7月20日：设计新架构 + 搭建骨架

### 上午（2小时）：架构设计

**动作1：画StateGraph状态图**

用纸或draw.io画出以下状态图，后续写代码时对照：

```
START → 主Agent节点(model_node)
  ├─ tool_call类型=普通工具 → 工具执行节点(tool_node) → 主Agent节点
  ├─ tool_call类型=网络搜索子图 → network_search_subgraph → 主Agent节点
  ├─ tool_call类型=数据库查询子图 → database_query_subgraph → 主Agent节点
  ├─ tool_call类型=知识库检索子图 → knowledge_rag_subgraph → 主Agent节点
  └─ 无tool_call（最终回答） → END
```

**动作2：定义自定义State**

创建文件 `agent/state.py`：

```python
"""主图的状态定义"""
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """主Agent的状态结构"""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    # 后续可扩展：current_agent, task_status, error_count 等
```

这个文件很短，但面试时要能解释：
- 为什么用 `TypedDict` 而不是 `dataclass`
- `Annotated` + `add_messages` 的作用（消息累加而非覆盖）

### 下午（2小时）：搭建测试框架

**动作3：初始化测试目录**

```bash
pip install pytest pytest-asyncio
```

创建 `tests/__init__.py`（空文件）

创建 `tests/conftest.py`：

```python
"""全局测试fixtures"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from langchain_core.messages import AIMessage, HumanMessage


@pytest.fixture
def mock_llm():
    """Mock LLM，避免测试时调用真实API"""
    llm = MagicMock()
    llm.ainvoke = AsyncMock()
    return llm


@pytest.fixture
def sample_messages():
    """样例消息列表"""
    return [HumanMessage(content="列出所有药品的销售数据")]
```

**动作4：创建 `.gitignore`**

```
__pycache__/
*.pyc
.idea/
.env
output/
updated/
data/chroma_db/
*.egg-info/
.pytest_cache/
```

### 今日产出

- [ ] `agent/state.py` — State定义
- [ ] `tests/__init__.py` + `tests/conftest.py` — 测试框架
- [ ] `.gitignore`
- [ ] 手画的StateGraph状态图（拍照保存）
- [ ] 验证：`pytest tests/ -v` 能跑通（虽然还没有测试用例）

---

## Day 11 — 7月21日：重写主Agent节点

### 上午（2小时）：实现主图

**动作1：创建 `agent/nodes.py`**

这个文件定义主Agent节点函数和路由函数：

```python
"""主图的节点函数"""
from langchain_core.messages import AIMessage
from agent.state import AgentState
from agent.llm import model


async def model_node(state: AgentState) -> dict:
    """主Agent节点：调用LLM，决定下一步行动"""
    # 绑定所有可用工具（包括子图入口工具）
    # model_with_tools = model.bind_tools([...])
    # response = await model_with_tools.ainvoke(state["messages"])
    # return {"messages": [response]}
    pass


def route_after_model(state: AgentState) -> str:
    """路由函数：根据LLM输出决定走向哪个节点"""
    last_message = state["messages"][-1]

    # 没有tool_call → 最终回答 → 结束
    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return "__end__"

    # 有tool_call → 根据工具名称路由
    tool_name = last_message.tool_calls[0]["name"]

    # 子图入口工具
    subgraph_mapping = {
        "search_internet": "network_search_subgraph",
        "query_database": "database_query_subgraph",
        "query_knowledge_base": "knowledge_rag_subgraph",
    }

    return subgraph_mapping.get(tool_name, "tool_node")
```

**动作2：创建 `agent/graph.py`**

```python
"""主StateGraph定义"""
from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import MemorySaver
from agent.state import AgentState
from agent.nodes import model_node, route_after_model


def build_graph():
    """构建并编译主图"""
    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("model_node", model_node)
    graph.add_node("tool_node", ...)  # Day 16 实现
    # 子图节点在 Day 12-14 添加

    # 设置入口
    graph.set_entry_point("model_node")

    # 条件路由
    graph.add_conditional_edges(
        "model_node",
        route_after_model,
        {
            "__end__": "__end__",
            "tool_node": "tool_node",
            "network_search_subgraph": "network_search_subgraph",
            "database_query_subgraph": "database_query_subgraph",
            "knowledge_rag_subgraph": "knowledge_rag_subgraph",
        }
    )

    return graph.compile(checkpointer=MemorySaver())
```

注意：今天的graph还跑不通（子图和工具节点还没实现），但骨架要搭好。

### 下午（2小时）：写路由测试

**动作3：创建 `tests/test_graph.py`**

```python
"""测试主图路由逻辑"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from agent.nodes import route_after_model


class TestRouteAfterModel:
    """测试 route_after_model 路由函数"""

    def test_no_tool_call_returns_end(self):
        """没有tool_call时应该返回__end__"""
        state = {
            "messages": [
                HumanMessage(content="你好"),
                AIMessage(content="你好！有什么可以帮你的？")
            ]
        }
        assert route_after_model(state) == "__end__"

    def test_search_tool_routes_to_network(self):
        """调用search_internet时应路由到网络搜索子图"""
        msg = AIMessage(content="", tool_calls=[
            {"name": "search_internet", "args": {"query": "药品趋势"}, "id": "1"}
        ])
        state = {"messages": [msg]}
        assert route_after_model(state) == "network_search_subgraph"

    def test_db_tool_routes_to_database(self):
        """调用query_database时应路由到数据库子图"""
        msg = AIMessage(content="", tool_calls=[
            {"name": "query_database", "args": {"question": "销量"}, "id": "2"}
        ])
        state = {"messages": [msg]}
        assert route_after_model(state) == "database_query_subgraph"

    def test_rag_tool_routes_to_knowledge(self):
        """调用query_knowledge_base时应路由到知识库子图"""
        msg = AIMessage(content="", tool_calls=[
            {"name": "query_knowledge_base", "args": {"question": "用法"}, "id": "3"}
        ])
        state = {"messages": [msg]}
        assert route_after_model(state) == "knowledge_rag_subgraph"

    def test_regular_tool_routes_to_tool_node(self):
        """调用普通工具（如generate_markdown）应路由到工具节点"""
        msg = AIMessage(content="", tool_calls=[
            {"name": "generate_markdown", "args": {"content": "test"}, "id": "4"}
        ])
        state = {"messages": [msg]}
        assert route_after_model(state) == "tool_node"
```

### 今日产出

- [ ] `agent/nodes.py` — 节点函数 + 路由函数
- [ ] `agent/graph.py` — 主图骨架
- [ ] `tests/test_graph.py` — 5个路由测试用例
- [ ] 验证：`pytest tests/test_graph.py -v` 全部通过

---

## Day 12 — 7月22日：重写子Agent — 网络搜索子图

### 上午（2小时）：实现子图

**动作1：创建 `agent/subgraphs/__init__.py`**（空文件）

**动作2：创建 `agent/subgraphs/network_search.py`**

```python
"""网络搜索子图"""
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from agent.llm import model
from tools.tavily_tool import internet_search


class SearchState(TypedDict):
    """搜索子图的状态"""
    messages: Annotated[Sequence[BaseMessage], add_messages]


async def search_agent_node(state: SearchState) -> dict:
    """搜索Agent节点：决定搜什么、怎么搜"""
    system_prompt = """你是一个专业的网络信息检索助手。
    根据用户问题从互联网检索相关信息。
    至少从3个角度检索，最多检索5次。"""

    model_with_tools = model.bind_tools([internet_search])
    response = await model_with_tools.ainvoke(
        [{"role": "system", "content": system_prompt}] + list(state["messages"])
    )
    return {"messages": [response]}


def search_route(state: SearchState) -> str:
    """判断是继续搜索还是返回结果"""
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "search_tools"
    return "__end__"


def build_network_search_subgraph():
    """构建网络搜索子图"""
    graph = StateGraph(SearchState)
    graph.add_node("search_agent", search_agent_node)
    graph.add_node("search_tools", ToolNode([internet_search]))

    graph.set_entry_point("search_agent")
    graph.add_conditional_edges("search_agent", search_route, {
        "search_tools": "search_tools",
        "__end__": "__end__",
    })
    graph.add_edge("search_tools", "search_agent")  # 工具执行后回到Agent

    return graph.compile()
```

**动作3：注册到主图**

在 `agent/graph.py` 中添加：

```python
from agent.subgraphs.network_search import build_network_search_subgraph

# 在 build_graph() 中：
graph.add_node("network_search_subgraph", build_network_search_subgraph())
```

### 下午（2小时）：写测试

**动作4：创建 `tests/test_network_agent.py`**

```python
"""测试网络搜索子图"""
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


class TestNetworkSearchSubgraph:

    def test_search_route_with_tool_call(self):
        """有tool_call时应路由到search_tools"""
        from agent.subgraphs.network_search import search_route
        msg = AIMessage(content="", tool_calls=[
            {"name": "internet_search", "args": {"query": "test"}, "id": "1"}
        ])
        state = {"messages": [msg]}
        assert search_route(state) == "search_tools"

    def test_search_route_without_tool_call(self):
        """无tool_call时应结束"""
        from agent.subgraphs.network_search import search_route
        msg = AIMessage(content="搜索结果如下...")
        state = {"messages": [msg]}
        assert search_route(state) == "__end__"

    @patch("tools.tavily_tool.tavily_client")
    def test_internet_search_returns_results(self, mock_client):
        """验证搜索工具能正确返回结果"""
        mock_client.search.return_value = {
            "results": [{"title": "Test", "url": "https://example.com", "content": "test content"}]
        }
        from tools.tavily_tool import internet_search
        result = internet_search.invoke({
            "query": "药品行业趋势",
            "topic": "general",
            "max_results": 3,
            "include_raw_content": False
        })
        assert "results" in result
```

### 今日产出

- [ ] `agent/subgraphs/__init__.py`
- [ ] `agent/subgraphs/network_search.py` — 网络搜索子图
- [ ] `tests/test_network_agent.py` — 3个测试用例
- [ ] `agent/graph.py` 中注册子图节点
- [ ] 验证：`pytest tests/test_network_agent.py -v` 通过

---

## Day 13 — 7月23日：重写子Agent — 数据库查询子图 + SQL安全加固

### 上午（2小时）：安全加固 + 子图实现

**动作1：重写 `tools/db_tools.py`**

关键改动：
1. 提取公共的 `_execute_and_format` 函数，消除 `get_table_data` 和 `execute_sql_query` 的重复代码
2. 添加SQL安全校验函数

```python
# 新增安全校验（加在文件顶部）
import re

DANGEROUS_KEYWORDS = re.compile(
    r'\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b',
    re.IGNORECASE
)

def validate_sql_readonly(query: str) -> str | None:
    """校验SQL是否为只读查询，返回None表示安全，否则返回拒绝原因"""
    if DANGEROUS_KEYWORDS.search(query):
        matched = DANGEROUS_KEYWORDS.search(query).group()
        return f"安全拒绝：禁止执行 {matched} 操作，只允许 SELECT 查询"
    return None


def _execute_and_format(sql: str, config: dict) -> str:
    """公共方法：执行SQL并格式化为CSV"""
    # 把原来 get_table_data 和 execute_sql_query 中重复的
    # 连接-执行-格式化逻辑提取到这里
    ...
```

**动作2：创建 `agent/subgraphs/database_query.py`**

结构与网络搜索子图类似，但加入 Human-in-the-loop：

```python
"""数据库查询子图"""
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode
from tools.db_tools import list_sql_tables, get_table_data, execute_sql_query


def build_database_query_subgraph():
    graph = StateGraph(DBQueryState)
    graph.add_node("db_agent", db_agent_node)
    graph.add_node("db_tools", ToolNode([list_sql_tables, get_table_data, execute_sql_query]))

    graph.set_entry_point("db_agent")
    graph.add_conditional_edges("db_agent", db_route, {
        "db_tools": "db_tools",
        "__end__": "__end__",
    })
    graph.add_edge("db_tools", "db_agent")

    # Human-in-the-loop：执行SQL前中断
    return graph.compile(interrupt_before=["db_tools"])
```

### 下午（2小时）：写安全测试

**动作3：创建 `tests/test_db_agent.py`**

这是最重要的测试文件，面试必问：

```python
"""测试数据库子图 + SQL安全"""
import pytest
from tools.db_tools import validate_sql_readonly


class TestSQLSecurity:
    """SQL安全校验测试"""

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM drugs",
        "SELECT d.name, s.quantity FROM drugs d JOIN sales s ON d.id = s.drug_id",
        "select count(*) from sales_records",
    ])
    def test_valid_select_queries_pass(self, sql):
        """合法的SELECT查询应该通过校验"""
        assert validate_sql_readonly(sql) is None

    @pytest.mark.parametrize("sql,keyword", [
        ("DROP TABLE drugs", "DROP"),
        ("DELETE FROM sales_records WHERE id=1", "DELETE"),
        ("UPDATE drugs SET price=0", "UPDATE"),
        ("INSERT INTO drugs VALUES (1,'test',10)", "INSERT"),
        ("ALTER TABLE drugs ADD COLUMN hack TEXT", "ALTER"),
        ("TRUNCATE TABLE drugs", "TRUNCATE"),
    ])
    def test_dangerous_queries_blocked(self, sql, keyword):
        """危险SQL操作应该被拦截"""
        result = validate_sql_readonly(sql)
        assert result is not None
        assert keyword in result

    def test_mixed_case_injection(self):
        """大小写混合的注入尝试也应该被拦截"""
        assert validate_sql_readonly("DrOp TaBlE drugs") is not None

    def test_sql_in_string_literal(self):
        """字符串中包含关键词的情况（已知边界case，记录在案）"""
        # 注意：这是一个简单的正则方案的已知局限
        # 更完善的方案需要用sqlparse做AST分析
        result = validate_sql_readonly("SELECT * FROM drugs WHERE name='DROP'")
        # 当前实现会误拦截这种情况，记录为已知限制
        # 面试时主动提这个点是加分项
```

### 今日产出

- [ ] `tools/db_tools.py` — 重写：安全校验 + 消除重复代码
- [ ] `agent/subgraphs/database_query.py` — 数据库查询子图（带 interrupt_before）
- [ ] `tests/test_db_agent.py` — 8+个安全测试用例
- [ ] `agent/graph.py` 中注册数据库子图
- [ ] 验证：`pytest tests/test_db_agent.py -v` 通过

---

## Day 14 — 7月24日：重写子Agent — 本地RAG（替代RAGFlow）

### 上午（2小时）：搭建本地RAG pipeline

**动作1：安装依赖**

```bash
pip install chromadb langchain-huggingface sentence-transformers
# 或者如果你用通义千问的Embedding：
pip install dashscope
```

**动作2：准备知识库文档**

创建 `knowledge_base/` 目录，放入3-5份药品相关的文档：

```
knowledge_base/
├── 药品使用说明.txt        # 写几种药品的用法用量
├── 药品存储规范.txt        # 温度、湿度、有效期等
└── 药品安全须知.txt        # 不良反应、禁忌症等
```

每个文件写300-500字即可，内容可以从网上找公开的药品说明书摘录。

**动作3：创建 `tools/rag_tools.py`**

```python
"""本地RAG工具 — 替代RAGFlow"""
from pathlib import Path
from langchain_core.tools import tool
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
# Embedding模型二选一：
# 方案A：HuggingFace本地模型（免费，首次下载较慢）
from langchain_huggingface import HuggingFaceEmbeddings
# 方案B：通义千问Embedding（需要API Key，速度快）
# from langchain_community.embeddings import DashScopeEmbeddings

from api.monitor import monitor

# 路径配置
PROJECT_ROOT = Path(__file__).parent.parent
KB_DIR = PROJECT_ROOT / "knowledge_base"
CHROMA_DIR = PROJECT_ROOT / "data" / "chroma_db"

# 初始化Embedding模型
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)


def init_vector_store() -> Chroma:
    """初始化或加载向量数据库"""
    if CHROMA_DIR.exists() and any(CHROMA_DIR.iterdir()):
        # 已有数据，直接加载
        return Chroma(persist_directory=str(CHROMA_DIR), embedding_function=embeddings)

    # 首次运行，建库
    loader = DirectoryLoader(str(KB_DIR), glob="**/*.txt", loader_cls=TextLoader,
                             loader_kwargs={"encoding": "utf-8"})
    documents = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        separators=["\n\n", "\n", "。", "；", " "]
    )
    chunks = splitter.split_documents(documents)

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(CHROMA_DIR)
    )
    return vectorstore


# 模块级初始化
vector_store = init_vector_store()
retriever = vector_store.as_retriever(search_kwargs={"k": 5})


@tool
def list_knowledge_bases() -> str:
    """列出知识库中的所有文档来源，供模型了解可用的内部知识范围"""
    monitor.report_tool("知识库文档列表查询工具：list_knowledge_bases")
    try:
        files = [f.name for f in KB_DIR.iterdir() if f.is_file()]
        if not files:
            return "知识库为空，没有可用文档"
        return "可用的知识库文档：" + "、".join(files)
    except Exception as e:
        return f"查询知识库异常：{str(e)}"


@tool
def query_knowledge_base(question: str) -> str:
    """根据问题检索知识库中的相关信息。用于查询企业内部的药品知识（非数据库数据）。
    :param question: 要检索的问题
    :return: 相关的知识片段
    """
    monitor.report_tool("知识库检索工具：query_knowledge_base",
                        args={"question": question})
    try:
        docs = retriever.invoke(question)
        if not docs:
            return "未找到相关信息"

        results = []
        for i, doc in enumerate(docs, 1):
            source = Path(doc.metadata.get("source", "未知")).name
            results.append(f"[来源: {source}]\n{doc.page_content}")

        return "\n\n---\n\n".join(results)
    except Exception as e:
        return f"知识库检索失败：{str(e)}"
```

### 下午（2小时）：子图 + 测试

**动作4：创建 `agent/subgraphs/knowledge_rag.py`**

结构与前两个子图类似：`rag_agent_node` → `rag_tools` → 循环或结束。

**动作5：创建 `tests/test_rag_agent.py`**

```python
"""测试本地RAG子图"""
import pytest
from pathlib import Path
import tempfile


class TestRAGTools:

    def test_list_knowledge_bases(self):
        """应该能列出知识库文档"""
        from tools.rag_tools import list_knowledge_bases
        result = list_knowledge_bases.invoke({})
        assert "可用的知识库文档" in result or "知识库为空" in result

    def test_query_returns_relevant_content(self):
        """检索应该返回与问题相关的内容"""
        from tools.rag_tools import query_knowledge_base
        result = query_knowledge_base.invoke({"question": "药品存储温度"})
        # 至少应该返回内容而不是空
        assert len(result) > 10

    def test_query_with_irrelevant_question(self):
        """完全无关的问题也应该正常返回（可能是不太相关的结果）"""
        from tools.rag_tools import query_knowledge_base
        result = query_knowledge_base.invoke({"question": "今天天气怎么样"})
        # 不应该报错
        assert isinstance(result, str)
```

### 今日产出

- [ ] `knowledge_base/` 目录 + 3-5份药品知识文档
- [ ] `tools/rag_tools.py` — 本地RAG工具（2个@tool）
- [ ] `agent/subgraphs/knowledge_rag.py` — 知识库检索子图
- [ ] `tests/test_rag_agent.py` — 3个测试用例
- [ ] `requirements.txt` 中去掉 `ragflow-sdk`，加上 `chromadb`、`langchain-huggingface`、`sentence-transformers`
- [ ] 删除 `tools/ragflow_tools.py` 和 `rawflow/` 目录
- [ ] 验证：`pytest tests/test_rag_agent.py -v` 通过

---

## Day 15 — 7月25日：重写流式输出 & Monitor集成

### 上午（2小时）：适配新的流式输出

**动作1：修改 `agent/main_agent.py`（或重命名为 `agent/runner.py`）**

原来的 `run_deep_agent` 函数需要重写，因为：
- 不再用 `create_deep_agent`，改为用 `build_graph()` 构建的图
- 流式输出从解析 chunk 的 `node_name` + `messages` 改为用 `astream_events`

```python
"""Agent执行器 — 替代原 main_agent.py 中的 run_deep_agent"""
from agent.graph import build_graph
from api.context import set_session_context, reset_session_context, set_thread_context
from api.monitor import monitor

# 编译图（模块级，只编译一次）
app = build_graph()


async def run_agent(task_query: str, session_id: str):
    """流式异步执行主Agent"""
    # session_dir创建、文件上传处理等逻辑保留，从原run_deep_agent搬过来
    # ...

    config = {"configurable": {"thread_id": session_id}}

    try:
        async for event in app.astream_events(
            {"messages": [{"role": "user", "content": task_query + path_instruction}]},
            config=config,
            version="v2"
        ):
            kind = event["event"]

            if kind == "on_chat_model_start":
                # Agent开始思考
                pass

            elif kind == "on_tool_start":
                # 工具调用开始 → 推送给前端
                tool_name = event.get("name", "unknown")
                monitor.report_tool(tool_name, event.get("data", {}).get("input", {}))

            elif kind == "on_chat_model_end":
                # 模型输出完成
                output = event["data"]["output"]
                if hasattr(output, "content") and output.content and not output.tool_calls:
                    # 最终回答
                    monitor.report_task_result(output.content)

    except Exception as e:
        monitor._emit("error", f"执行Agent异常：{str(e)}")
    finally:
        reset_session_context(session_dir_token, session_id_token)
```

### 下午（2小时）：适配Server

**动作2：修改 `api/server.py`**

把 import 从 `from agent.main_agent import run_deep_agent` 改为 `from agent.runner import run_agent`。

**动作3：手动测试WebSocket推送**

1. 启动服务：`python -m uvicorn api.server:app --reload`
2. 用简单的WebSocket客户端连接 `ws://localhost:8000/ws/test_session`
3. 用curl发请求：`curl -X POST http://localhost:8000/api/task -H "Content-Type: application/json" -d '{"query": "列出数据库中的所有表", "thread_id": "test_session"}'`
4. 观察WebSocket是否收到 `monitor_event` 消息

### 今日产出

- [ ] `agent/runner.py`（或重写 `agent/main_agent.py`）— 基于 `astream_events` 的执行器
- [ ] `api/server.py` — 更新import
- [ ] 手动测试WebSocket推送正常
- [ ] 删除原 `agent/main_agent.py` 中的旧逻辑

---

## Day 16 — 7月27日：工具链迁移 & 路径系统

### 上午（2小时）：工具节点 + 路径清理

**动作1：在主图中实现 `tool_node`**

在 `agent/graph.py` 中，用 LangGraph 的 `ToolNode` 统一处理普通工具调用：

```python
from langgraph.prebuilt import ToolNode
from tools.markdown_tools import generate_markdown
from tools.pdf_tools import convert_md_to_pdf
from tools.upload_file_read_tool import read_file_content

direct_tools = [generate_markdown, convert_md_to_pdf, read_file_content]
graph.add_node("tool_node", ToolNode(direct_tools))
graph.add_edge("tool_node", "model_node")  # 工具执行后回到主Agent
```

**动作2：清理工具文件中的教学注释**

逐个文件，把所有 `# 步骤1：xxx`、`# 确保要捕捉异常信息...` 这类教学注释删掉，替换为简洁的 docstring。

### 下午（2小时）：路径统一 + 清理

**动作3：清理 `tools/markdown_tools.py` 和 `tools/pdf_tools.py`**

- 删除底部的 `if __name__ == "__main__"` 测试代码
- 删除 `print(f"⚠️ ...")` 等调试输出
- 统一用 `pathlib.Path`

**动作4：清理 `tools/tavily_tool.py`**

删除大量空行和教学注释，保留核心逻辑。

### 今日产出

- [ ] `agent/graph.py` — 添加 tool_node + 所有边
- [ ] 6个工具文件全部清理完毕（零教学注释）
- [ ] 验证：`pytest tests/ -v` 全部通过（确保清理没有破坏功能）

---

## Day 17 — 7月28日：场景收窄 & Prompt重写

### 上午（2小时）：重写Prompt

**动作1：重写 `prompt/prompts.yml`**

```yaml
main_agent:
  system_prompt: |
    你是一个药品销售数据分析智能助手，帮助企业分析药品销售数据、检索药品知识、获取行业信息。

    你可以调度以下专业工具：
    1. 数据库查询工具 — 查询药品信息表、库存表、销售记录表
    2. 知识库检索工具 — 检索企业内部的药品使用说明、存储规范等文档
    3. 网络搜索工具 — 获取药品行业新闻、市场趋势等公开信息

    工作流程：
    1. 分析用户问题，判断需要从哪些数据源获取信息
    2. 调用相应工具获取数据
    3. 整合信息，给出分析结论
    4. 如用户要求生成文档，使用文件生成工具输出

    约束：
    - 先获取数据，再生成文档，不得用占位符内容生成文件
    - 数据库操作仅允许查询，禁止修改数据
    - 使用指定的工作目录保存生成文件

sub_agents:
  network_search:
    system_prompt: |
      你是药品行业信息检索助手。从互联网检索药品行业相关信息。
      搜索策略：从宏观趋势到具体数据，至少检索3个角度，最多5次。

  database_query:
    system_prompt: |
      你是药品销售数据查询助手。通过SQL查询企业的药品数据库。
      工作流程：先用list_sql_tables查看可用表 → 用get_table_data预览表结构 → 用execute_sql_query执行精确查询。
      所有查询必须是只读SELECT语句。

  knowledge_rag:
    system_prompt: |
      你是药品知识库检索助手。从企业内部文档中检索药品相关知识。
      工作流程：先用list_knowledge_bases了解可用文档 → 用query_knowledge_base检索具体问题。
      至少从3个角度提问，保留检索到的原始信息。
```

### 下午（2小时）：场景用例

**动作2：创建 `docs/use_cases.md`**

```markdown
# 典型使用场景

## 场景1：销售趋势分析
用户："分析上季度哪些药品销量下降超过20%"
预期流程：数据库子图（查销售记录表）→ 主Agent分析 → 生成Markdown报告

## 场景2：药品知识查询
用户："阿莫西林的存储温度要求是什么？"
预期流程：知识库子图（检索存储规范文档）→ 主Agent整理回答

## 场景3：竞品对比分析
用户："对比我们的布洛芬和市场上竞品的情况"
预期流程：数据库子图（查我方数据）→ 网络搜索子图（查竞品公开信息）→ 主Agent整合分析
```

**动作3：修改 `agent/prompts.py` 加载新prompt**

适配新的 `prompts.yml` 结构。

### 今日产出

- [ ] `prompt/prompts.yml` — 全新的prompt配置
- [ ] `docs/use_cases.md` — 3个典型场景用例
- [ ] `agent/prompts.py` 或 `agent/graph.py` 中加载新prompt
- [ ] 手动测试：用3个场景用例分别跑一遍，验证路由正确

---

## Day 18 — 7月29日：端到端测试 & Debug

### 全天（4小时）：系统测试

**动作1：按场景用例跑完整流程**

逐个测试 `docs/use_cases.md` 中的3个场景：
1. 启动服务
2. 发送请求
3. 检查：路由是否正确？工具是否被调用？结果是否合理？WebSocket推送是否正常？

**动作2：测试多轮对话**

同一个 `thread_id` 下连续提问：
- 第一轮："列出所有药品"
- 第二轮："其中哪个销量最高？"（应该能利用上一轮的上下文）

**动作3：测试并发**

用两个不同的 `thread_id` 同时发请求，验证 ContextVar 隔离正常。

**动作4：运行全部单元测试**

```bash
pytest tests/ -v --tb=short
```

修复所有失败的测试。

**动作5：记录Bug清单**

创建 `docs/bugs.md`，记录发现的问题和修复方案。明天集中修复。

### 今日产出

- [ ] 3个场景用例手动测试通过
- [ ] 多轮对话测试通过
- [ ] 并发测试通过
- [ ] `pytest tests/ -v` 全部绿色
- [ ] `docs/bugs.md`（如果有bug）

---

## Day 19 — 7月30日：代码整理 & 重构收尾

### 上午（2小时）：清理代码

**动作1：删除所有废弃文件**

```bash
# 删除旧文件
rm -rf agent/subagents/
rm -f tools/ragflow_tools.py
rm -rf rawflow/
rm -f api/1.py api/deep_agent_02_fixed.py
rm -f 学习笔记.md server_学习笔记.md help.md 项目搭建与运行指南.md 项目步骤

# 删除所有 __pycache__
find . -type d -name __pycache__ -exec rm -rf {} +
```

**动作2：清理 `requirements.txt`**

只保留实际使用的依赖，删除不再需要的（如 `ragflow-sdk`、`deepagents`）。

建议的最终依赖列表：
```
fastapi
uvicorn
langchain
langchain-core
langchain-openai
langgraph
langgraph-checkpoint
chromadb
langchain-huggingface
sentence-transformers
tavily-python
mysql-connector-python
python-dotenv
pyyaml
python-multipart
python-docx
md2pdf
loguru          # 第四阶段用，先加上
pytest          # dev dependency
pytest-asyncio  # dev dependency
```

### 下午（2小时）：添加类型注解 + 最终验证

**动作3：给关键函数加类型注解**

重点文件：`agent/nodes.py`、`agent/graph.py`、`agent/runner.py`

**动作4：最终验证清单**

- [ ] `pytest tests/ -v` 全部通过
- [ ] `python -c "from agent.graph import build_graph; g = build_graph(); print('Graph OK')"` 成功
- [ ] 手动跑一个完整请求，从API到结果返回正常
- [ ] `grep -r "deepagents" .` 返回空（确认完全去除依赖）
- [ ] `grep -r "ragflow" .` 返回空（确认完全替换）
- [ ] 项目中没有 `__pycache__` 目录

### 今日产出

- [ ] 废弃文件全部删除
- [ ] `requirements.txt` 精简到只包含实际依赖
- [ ] 关键函数有类型注解
- [ ] 最终验证清单全部通过
- [ ] **第三阶段完成！**
