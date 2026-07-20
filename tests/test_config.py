import pytest
from app.config import Settings

def test_settings_with_valid_env(monkeypatch):
    """给全必填项，Settings 应该正常创建。"""
    monkeypatch.setenv("LLM_MODEL", "qwen-max")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("MYSQL_USER", "root")
    monkeypatch.setenv("MYSQL_PASSWORD", "123456")
    monkeypatch.setenv("MYSQL_DATABASE", "test_db")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    monkeypatch.setenv("EMBED_MODEL", "text-embedding-v3")

    s = Settings(_env_file=None)

    assert s.llm_model == "qwen-max"
    assert s.mysql_port == 3306
    assert s.llm_timeout == 60

def test_settings_missing_required_field(monkeypatch):
    """缺少必填项时，应该抛出 ValidationError。"""
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    with pytest.raises(Exception):
        Settings(_env_file=None)