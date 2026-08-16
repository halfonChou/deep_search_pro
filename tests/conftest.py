"""pytest 根配置：共享 fixture 放这里（当前留空）。"""

import pytest

from app.config import Settings


@pytest.fixture
def settings(tmp_path):
    """一份干净的、指向临时目录的测试配置。

    _env_file=None：不读项目根目录的 .env，避免测试受本地环境影响。
    必填项在这里手工给假值——Settings 里这几个字段没有默认值，不给会 ValidationError。
    """
    return Settings(
        _env_file=None,
        llm_base_url="https://example.com/v1",
        llm_api_key="test-key",
        mysql_password="test-pwd",
        mysql_database="test_db",
        tavily_api_key="tvly-test",
        embed_model="text-embedding-v3",
        # ★ 关键：所有落盘路径都指到 tmp_path，测试不会污染真实的 data/ 目录
        data_dir=tmp_path,
        chroma_dir=tmp_path / "chroma",
        checkpoint_db=tmp_path / "checkpoints.sqlite",
        report_index_file=tmp_path / "index.jsonl",
    )
