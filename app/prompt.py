from pathlib import Path

import yaml


def load_prompt(path: Path | None = None) -> dict:
    """
        加载提示词1的yaml文件返回字典
    """
    if path is None:
        path = Path(__file__).resolve().parents[1] / "prompts" / "prompts.yml"

    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def main_agent_prompt():
    return load_prompt()["main_agent"]["system_prompt"]

# 获取所有子agent的prompt
def sub_agent_prompts():
    return load_prompt()["sub_agents"]
