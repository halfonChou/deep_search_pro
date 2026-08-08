from __future__ import annotations

from langchain_core.tools import tool

from app.config import Settings
from app.infra.db import Database


def build_sql_tools(db: Database, settings: Settings):
    @tool
    async def list_sql_table():
        """查询当前数据中中所有可以使用的表名"""
        columns, rows = await db.fetch("SHOW TABLES")
        if not rows:
            return "无可用的表"
        table_name = [row[0] for row in rows]
        return f"可用的表有:{','.join(table_name)}"

    @tool
    async def describe_table(table_name: str) -> str:
        """查看指定表的列结构（列名 + 类型），写 SQL 前先看表结构。"""

        columns, rows = await db.fetch(f"SHOW COLUMNS FROM `{table_name}`")

        if not rows:
            return f"数据表 {table_name} 不存在或没有列"

        header = "列名,类型"
        data = "\n".join(",".join([str(row[0]), str(row[1])]) for row in rows)
        return f"{header}\n{data}"

    @tool
    async def get_table_data(table_name: str):
        """查询指定表的数据，返回 CSV 格式。"""

        sql = f"SELECT * FROM `{table_name}` LIMIT {settings.sql_row_limit}"
        columns, rows = await db.fetch(sql)

        if not rows:
            return f"数据表 {table_name} 为空，没有数据"

        header = ",".join(columns)
        data = "\n".join(",".join(str(val) for val in row) for row in rows)
        return f"{header}\n{data}"

    @tool
    async def execute_sql_query(query: str):
        """执行自定义 SQL 查询，返回 CSV 格式。"""


        columns, rows = await db.fetch(query)

        if not rows:
            return f"查询没有结果， SQL：{query}"

        header = ",".join(columns)
        data = "\n".join(",".join(str(val) for val in row) for row in rows)
        return f"{header}\n{data}"

    return [list_sql_table, describe_table, get_table_data, execute_sql_query]
