"""结构化日志配置（Day 11）。

核心设计：
1. 用 contextvars 在异步上下文中传递 thread_id，
   logging.Filter 自动把它注入每条日志。
2. 并发两个任务时，日志里的 thread_id 能区分是哪个会话的。
3. 格式：时间 | 级别 | thread_id | 模块名 | 消息

为什么用 contextvars 而不是 threading.local：
- asyncio 协程在同一个线程里并发，threading.local 对所有协程返回同一个值。
- contextvars 是 per-task 的，每个 asyncio.Task 有自己的上下文副本，天然适配异步。
"""

import logging
import sys
from contextvars import ContextVar

# 当前请求的 thread_id，在 TaskService._run 入口设置
current_thread_id: ContextVar[str] = ContextVar("current_thread_id", default="-")


class ThreadIdFilter(logging.Filter):
    """把 contextvars 里的 thread_id 注入到每条 LogRecord。

    这样 Formatter 里用 %(thread_id)s 就能拿到，
    不需要每个 logger.info() 手写 thread_id=xxx。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.thread_id = current_thread_id.get("-")  # type: ignore[attr-defined]
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """初始化全局日志配置。在 lifespan 里调一次即可。"""
    fmt = "%(asctime)s | %(levelname)-7s | tid=%(thread_id)s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    handler.addFilter(ThreadIdFilter())

    root = logging.getLogger()
    root.setLevel(level)

    # 避免重复添加 handler（热重载场景）
    if not any(isinstance(h, logging.StreamHandler) and h.stream is sys.stdout
               for h in root.handlers):
        root.addHandler(handler)

    # 降低第三方库的日志噪音
    for noisy in ("httpcore", "httpx", "chromadb", "urllib3", "aiosqlite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
