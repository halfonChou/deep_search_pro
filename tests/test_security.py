"""安全集成测试。

覆盖：路径穿越拦截、鉴权拦截、CORS 配置。
按当前 API 契约编写：query 参数用 thread_id（服务端推导路径）+ Authorization 鉴权。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


def _make_test_settings(data_dir: Path, **overrides) -> Settings:
    """构造测试用 Settings，填入必要默认值。"""
    defaults = {
        "llm_model": "test",
        "llm_base_url": "http://localhost",
        "llm_api_key": "test",
        "mysql_password": "test",
        "mysql_database": "test",
        "tavily_api_key": "test",
        "embed_model": "test",
        "api_token": "test_secret",
        "cors_origins": ["http://localhost:3000"],
        "data_dir": data_dir,  # 关键：会话目录在 data_dir/sessions/<thread_id>
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture
def client(tmp_path: Path):
    settings = _make_test_settings(tmp_path)
    get_settings.cache_clear()
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings

    yield TestClient(app)

    get_settings.cache_clear()


@pytest.fixture
def auth_header():
    return {"Authorization": "Bearer test_secret"}


# =========================================================================
# 鉴权测试
# =========================================================================

class TestAuth:

    def test_no_token_rejected(self, client: TestClient) -> None:
        """不带 token 访问文件接口 → 401"""
        resp = client.get("/files/list", params={"thread_id": "abc"})
        assert resp.status_code == 401

    def test_wrong_token_rejected(self, client: TestClient) -> None:
        """错误 token → 401"""
        resp = client.get(
            "/files/list",
            params={"thread_id": "abc"},
            headers={"Authorization": "Bearer wrong_token"},
        )
        assert resp.status_code == 401

    def test_correct_token_accepted(self, client: TestClient, auth_header) -> None:
        """正确 token → 不是 401"""
        resp = client.get(
            "/files/list",
            params={"thread_id": "abc"},
            headers=auth_header,
        )
        assert resp.status_code != 401


# =========================================================================
# 路径穿越测试
# =========================================================================

class TestPathTraversal:

    def test_dotdot_blocked(self, client: TestClient, auth_header, tmp_path) -> None:
        """../../ 穿越 → 403"""
        resp = client.get(
            "/files/download",
            params={"filename": "../../etc/passwd", "thread_id": "t1"},
            headers=auth_header,
        )
        assert resp.status_code == 403

    def test_absolute_path_blocked(self, client: TestClient, auth_header, tmp_path) -> None:
        """/etc/passwd 绝对路径 → 403"""
        resp = client.get(
            "/files/download",
            params={"filename": "/etc/passwd", "thread_id": "t1"},
            headers=auth_header,
        )
        assert resp.status_code == 403

    def test_empty_filename_blocked(self, client: TestClient, auth_header, tmp_path) -> None:
        """空文件名 → 400"""
        resp = client.get(
            "/files/download",
            params={"filename": "", "thread_id": "t1"},
            headers=auth_header,
        )
        assert resp.status_code == 400

    def test_normal_file_allowed(self, client: TestClient, auth_header, tmp_path) -> None:
        """正常文件名，文件不存在 → 404（不是 403，说明路径校验通过了）"""
        resp = client.get(
            "/files/download",
            params={"filename": "report.md", "thread_id": "t1"},
            headers=auth_header,
        )
        assert resp.status_code == 404


# =========================================================================
# 上传校验测试
# =========================================================================

class TestUpload:

    def test_forbidden_extension(self, client: TestClient, auth_header, tmp_path) -> None:
        """.exe 文件 → 400"""
        resp = client.post(
            "/files/upload",
            params={"thread_id": "t1"},
            headers=auth_header,
            files={"file": ("malware.exe", b"evil content")},
        )
        assert resp.status_code == 400

    def test_allowed_extension(self, client: TestClient, auth_header, tmp_path) -> None:
        """.md 文件 → 上传成功"""
        resp = client.post(
            "/files/upload",
            params={"thread_id": "t1"},
            headers=auth_header,
            files={"file": ("report.md", b"# Hello")},
        )
        assert resp.status_code == 200
        assert resp.json()["filename"] == "report.md"
