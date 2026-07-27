from __future__ import annotations

from langchain_core.tools import tool

from app.agents.events import AgentEvent
from app.config import Settings
from app.infra.db import Database
from app.infra.emitter import EventEmitter
from app.tools.sql_safety import assert_read_only, assert_table_allowed, enforce_limit


def build_sql_tools(db: Database, emitter: EventEmitter, settings: Settings):

    @tool
    async def list_sql_table():
        """查询当前数据中中所有可以使用的表名"""

        await emitter.emit(AgentEvent(
            type="tool_start",
            thread_id="",
            message = "正在查询数据库表列表"
        ))

        try:
            columns, rows = db.fetch("SHOW TABLES")
            if not rows:
                return "无可用的表"
            table_name = [row[0] for row in rows]
            return f"可用的表有:{','.join(table_name)}"
        finally:
            await emitter.emit(AgentEvent(
                type="tool_end",
                thread_id="",
                message="表列表查询完成",
                data={"tool": list_sql_table}
            ))

    @tool
    async def get_table_data(table_name: str) -> str:
        """查询指定表的数据，返回 CSV 格式。"""
        await emitter.emit(AgentEvent(
            type="tool_start", thread_id="",
            data={"tool": "get_table_data", "table_name": table_name},
        ))
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
        finally:
            await emitter.emit(AgentEvent(
                type="tool_end", thread_id="",
                message=f"查询表 {table_name}成功，正在返回结果",
                data={"tool": "get_table_data"},
            ))

    @tool
    async def execute_sql_query(query: str):
        """执行自定义 SQL 查询，返回 CSV 格式。"""
        await emitter.emit(AgentEvent(
            type="tool_start", thread_id="",
            message="正在查询sql语句"
        ))

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
        finally:
            await emitter.emit(AgentEvent(
                type="tool_end", thread_id="",
                data={"tool": "execute_sql_query"},
                message="查询成功"
            ))

    return [list_sql_table, get_table_data, execute_sql_query]
