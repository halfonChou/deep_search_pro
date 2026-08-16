from __future__ import annotations

import logging
from typing import Annotated

from langchain.tools import ToolRuntime
from langchain_core.tools import InjectedToolArg, tool

from app.config import Settings
from app.infra.db import Database
from app.tools._offload import offload_if_large
from app.tools.sql_safety import assert_read_only, assert_table_allowed, enforce_limit

logger = logging.getLogger(__name__)

# ★★ 为什么这些校验要在工具内部再做一遍（纵深防御）：
# SqlGuardMiddleware 挂在**主图**的中间件栈上，只读校验 + 补 LIMIT + 表白名单都在那儿。
# 但 database-query 是独立编译的 StateGraph，它的 ToolNode **不经过主图中间件**——
# 也就是说这些工具在子图里跑的时候，上面那三道闸一道都没生效。
# 实测确认过：子图里执行的 SQL 全都没有被补上 LIMIT。
# 安全校验不能依赖「调用方一定会先检查」，工具自己是最后一道防线。


def build_sql_tools(db: Database, settings: Settings):
    @tool
    async def list_sql_table():
        """查询当前数据中中所有可以使用的表名"""
        logger.info("[sql] list_sql_table")
        columns, rows = await db.fetch("SHOW TABLES")
        if not rows:
            return "无可用的表"
        table_name = [row[0] for row in rows]
        return f"可用的表有:{','.join(table_name)}"

    @tool
    async def describe_table(table_name: str) -> str:
        """查看指定表的列结构（列名 + 类型），写 SQL 前先看表结构。"""

        assert_table_allowed(table_name, settings.sql_table_allowlist)   # ★ 纵深防御
        logger.info("[sql] describe_table | table=%s", table_name)
        columns, rows = await db.fetch(f"SHOW COLUMNS FROM `{table_name.strip().strip('`')}`")

        if not rows:
            return f"数据表 {table_name} 不存在或没有列"

        header = "列名,类型"
        data = "\n".join(",".join([str(row[0]), str(row[1])]) for row in rows)
        return f"{header}\n{data}"

    @tool
    async def get_table_data(
        table_name: str,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg] = None,
    ):
        """查询指定表的数据，返回 CSV 格式。"""

        assert_table_allowed(table_name, settings.sql_table_allowlist)   # ★ 纵深防御
        sql = f"SELECT * FROM `{table_name.strip().strip('`')}` LIMIT {settings.sql_row_limit}"
        logger.info("[sql] get_table_data | %s", sql)
        columns, rows = await db.fetch(sql)
        logger.info("[sql] get_table_data 返回 %d 行", len(rows))

        if not rows:
            return f"数据表 {table_name} 为空，没有数据"

        header = ",".join(columns)
        data = "\n".join(",".join(str(val) for val in row) for row in rows)
        text = f"{header}\n{data}"

        # Day 10：大结果落盘卸载到 /scratch/（L0），只回摘要
        return await offload_if_large(
            text, runtime=runtime, hint="sql-table", settings=settings,
        )

    @tool
    async def execute_sql_query(
        query: str,
        runtime: Annotated[ToolRuntime | None, InjectedToolArg] = None,
    ):
        """执行自定义 SQL 查询，返回 CSV 格式。"""

        # ★ 纵深防御：子图不走 SqlGuardMiddleware，这两道闸只能在这里补。
        assert_read_only(query)
        query = enforce_limit(query, settings.sql_row_limit)

        # ★ 子 Agent 内部的工具调用不会出现在主图的事件流里，
        # 所以这条日志是唯一能看到「模型到底写了什么 SQL」的地方。零结果排查全靠它。
        logger.info("[sql] execute_sql_query | SQL=%s", " ".join(query.split()))
        columns, rows = await db.fetch(query)
        logger.info("[sql] execute_sql_query 返回 %d 行", len(rows))

        if not rows:
            # 零结果时给出可操作的下一步，而不是让模型直接放弃。
            # 注意：只提示「怎么查」，不告诉它答案是什么。
            return (
                f"查询返回 0 行。SQL：{query}\n"
                f"排查建议：先用 SELECT DISTINCT 看某个字段的真实取值，"
                f"再据此调整 WHERE 条件。中文字段（药品名、剂型、区域）的实际写法"
                f"常和你的猜测不一致，用 LIKE '%关键词%' 比用 = 更稳妥。"
            )

        header = ",".join(columns)
        data = "\n".join(",".join(str(val) for val in row) for row in rows)
        text = f"{header}\n{data}"

        # Day 10：大结果落盘卸载到 /scratch/（L0），只回摘要
        return await offload_if_large(
            text, runtime=runtime, hint="sql-query", settings=settings,
        )

    return [list_sql_table, describe_table, get_table_data, execute_sql_query]
