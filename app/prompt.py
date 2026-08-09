from pathlib import Path

import yaml


def load_prompt(path: Path | None = None) -> dict:
    """加载提示词 yaml 文件，返回字典。"""
    if path is None:
        path = Path(__file__).resolve().parents[1] / "prompts" / "prompts.yml"

    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


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