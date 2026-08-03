from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    llm_timeout: int = 60
    llm_max_retries: int = 5

    # MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str
    mysql_database: str
    mysql_pool_min: int = 1
    mysql_pool_max: int = 5

    #Tavily
    tavily_api_key: str

    # RAG
    embed_model: str
    chroma_dir: Path = Path("data/chroma")
    rag_chunk_size: int = 800
    rag_chunk_overlap: int = 120

    # 运行
    data_dir: Path = Path("data")
    checkpoint_db: Path = Path("data/checkpoints.sqlite")
    max_concurrent_tasks: int = 5
    event_queue_maxsize: int = 1000

    # 安全
    cors_origins: list[str] = ["http://localhost:3000"]
    api_token: str | None = None
    sql_table_allowlist: list[str] = []
    sql_row_limit: int = 100

    model_call_run_limit: int = 30  # 单次运行最多调模型 30 次
    model_call_thread_limit: int = 100  # 单个会话累计最多 100 次
    tool_call_run_limit: int = 40  # 单次运行最多调工具 40 次
    tool_call_thread_limit: int = 150  # 单个会话累计最多 150 次
    search_tool_run_limit: int = 5  # 搜索工具单独限流，因为最贵
    sql_tool_run_limit: int = 10  # SQL 工具单独限流

    budget_max_tokens: int = 200_000  # 一次运行最多消耗 20 万 token
    budget_max_cost_usd: float = 1.0  # 最多花 1 美元
    price_per_1m_input: float = 0.5  # 输入 token 单价，按你用的模型填
    price_per_1m_output: float = 2.0  # 输出 token 单价

    tool_retry_max: int = 3  # 最多重试 3 次
    tool_retry_initial_delay: float = 1.0  # 第一次重试等 1 秒
    tool_retry_backoff: float = 2.0  # 每次翻倍：1s → 2s → 4s
    fallback_models: list[str] = []  # 降级模型链，空表示不降级

    summarize_trigger_tokens: int = 60_000  # 超过 6 万 token 触发摘要
    summarize_keep_messages: int = 20  # 摘要后保留最近 20 条消息
    summarize_model: str | None = None  # 摘要用便宜的小模型，None 就用主模型
    context_edit_trigger_tokens: int = 80_000  # 超过 8 万 token 触发硬裁剪
    context_edit_keep_recent: int = 3  # 硬裁剪保留最近 3 条

    # 安全审批
    hitl_enabled: bool = True  # 是否开启人工审批
    hitl_interrupt_tools: list[str] = ["execute_sql_query"]  # 哪些工具需要审批

    # 会话
    session_ttl_hours: int = 24  # 会话过期时间

    # 文件分层（§1.6）
    offload_threshold_bytes: int = 4096  # 工具结果超 4KB 就落盘
    offload_summary_chars: int = 200  # 回给上下文的摘要长度
    scratch_dir: str = "/scratch"  # 虚拟文件系统草稿目录
    report_index_file: Path = Path("data/index.jsonl")  # 报告索引路径
    report_index_query_limit: int = 20  # 查报告一次最多返回 20 条

@lru_cache
def get_settings() -> Settings:
    return Settings()
