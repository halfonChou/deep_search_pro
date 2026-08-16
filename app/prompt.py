from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

# ★ 为什么要注入日期：
# 大模型对"现在"的认知停在训练截止日。不显式告诉它今天几号，它构造
# 「近三个月市场行情」这类查询时会按训练时的年份来写——实测它查了
# 2024 年 Q2，而当时是 2026 年 8 月，检索结果直接归零。
# 涉及"最新""近期""本季度"的判断全都受影响，不只是搜索。
_TZ = ZoneInfo("Asia/Shanghai")


def _runtime_vars() -> dict[str, str]:
    now = datetime.now(_TZ)
    return {
        "{{TODAY}}": now.strftime("%Y年%m月%d日"),
        "{{YEAR}}": str(now.year),
        "{{YEAR_MONTH}}": now.strftime("%Y年%m月"),
    }


def _inject(obj):
    """递归地把 {{TODAY}} 这类占位符替换成真实值。

    prompts.yml 里是嵌套 dict，system_prompt 和 description 都可能用到，
    所以走一遍递归，而不是只处理某个固定字段。
    """
    if isinstance(obj, str):
        for placeholder, value in _runtime_vars().items():
            obj = obj.replace(placeholder, value)
        return obj
    if isinstance(obj, dict):
        return {k: _inject(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_inject(v) for v in obj]
    return obj


def load_prompt(path: Path | None = None) -> dict:
    """加载提示词 yaml 文件，返回字典（已注入运行时变量）。"""
    if path is None:
        path = Path(__file__).resolve().parents[1] / "prompts" / "prompts.yml"

    with open(path, encoding="utf-8") as f:
        return _inject(yaml.safe_load(f))


def main_agent_prompt():
    return load_prompt()["main_agent"]["system_prompt"]


def sub_agent_prompts():
    return load_prompt()["sub_agents"]


def sub_agent_prompt(name: str) -> dict:
    prompts = load_prompt()["sub_agents"]
    if name not in prompts:
        raise KeyError(
            f"prompts.yml 的 sub_agents 下找不到 '{name}'。"
            f"现有的键是: {list(prompts)}。"
            f"注意：yaml 键用连字符（database-query），Python 模块名用下划线。"
        )
    return prompts[name]
