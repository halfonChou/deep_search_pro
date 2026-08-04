from __future__ import annotations

from langchain_core.tools import tool

from app.config import Settings
from app.infra.db import Database
from app.tools.sql_safety import assert_read_only, assert_table_allowed, enforce_limit


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
    async def get_table_data(table_name: str) -> str:
        """查询指定表的数据，返回 CSV 格式。"""
        try:
            # 安全校验：表名合法 + 在白名单内
            assert_table_allowed(table_name, settings.sql_table_allowlist)

            # 表名不能参数化，但已通过白名单校验，安全
            sql = f"SELECT * FROM `{table_name}` LIMIT {settings.sql_row_limit}"
            columns, rows = await db.fetch(sql)

            if not rows:
                return f"数据表 {table_name} 为空，没有数据"

            header = ",".join(columns)
            data = "\n".join(",".join(str(val) for val in row) for row in rows)
            return f"{header}\n{data}"
        except ValueError as e:
            return f"安全校验失败：{e}"
        except Exception as e:
            return f"查询出现异常：{e}"
    @tool
    async def execute_sql_query(query: str):
        """执行自定义 SQL 查询，返回 CSV 格式。"""

        try:
            assert_read_only(query)
            query = enforce_limit(query, settings.sql_row_limit)

            columns, rows = await  db.fetch(query)

            if not rows:
                return f"查询没有结果，SQL：{query}"

            header = ",".join(columns)
            data = "\n".join(",".join(str(val) for val in row) for row in rows)
            return f"{header}\n{data}"

        except ValueError as e:
            return f"SQL 安全校验失败 {e}"
        except TimeoutError as e:
            return f"SQL 查询超时 {e}"
        except Exception as e:
            return f"SQL 查询失败 {e}"

    return [list_sql_table, get_table_data, execute_sql_query]
