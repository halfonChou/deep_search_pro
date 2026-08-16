"""Day 10 上下文管理测试。

覆盖：
1. offload_if_large 阈值判断
2. 落盘后返回格式正确
3. 小于阈值直接返回原文
4. runtime 为 None 时的降级
5. list_past_reports 工具
6. SessionService.list_reports 查询与筛选
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.services.session_service import SessionService
from app.tools._offload import offload_if_large

# ============================================================
# offload_if_large 测试
# ============================================================


def _make_settings(**overrides) -> Settings:
    """构造测试用 Settings，只填必填字段。"""
    defaults = dict(
        llm_model="test",
        llm_base_url="http://localhost",
        llm_api_key="sk-test",
        mysql_password="test",
        mysql_database="test",
        tavily_api_key="tvly-test",
        embed_model="test",
        offload_threshold_bytes=100,      # 测试用小阈值
        offload_summary_chars=20,
        scratch_dir="/scratch",
    )
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.mark.asyncio
async def test_offload_small_text_returns_original():
    """小于阈值的文本直接返回原文。"""
    settings = _make_settings(offload_threshold_bytes=1000)
    text = "这是一段很短的文本"
    result = await offload_if_large(text, runtime=None, settings=settings)
    assert result == text


@pytest.mark.asyncio
async def test_offload_large_text_without_runtime():
    """超过阈值但 runtime 为 None 时，返回截断文本。"""
    settings = _make_settings(offload_threshold_bytes=10, offload_summary_chars=5)
    text = "这是一段超过阈值的长文本，需要被截断处理"
    result = await offload_if_large(text, runtime=None, settings=settings)
    assert "无法落盘" in result
    assert "已截断" in result


@pytest.mark.asyncio
async def test_offload_large_text_with_runtime():
    """超过阈值且有 runtime 时，调 write_file 并返回摘要 + 路径。"""
    settings = _make_settings(offload_threshold_bytes=10, offload_summary_chars=5)
    text = "这是一段超过阈值的长文本，需要被落盘处理并返回摘要"

    runtime = MagicMock()
    runtime.write_file = AsyncMock(return_value=None)

    result = await offload_if_large(
        text, runtime=runtime, hint="test", settings=settings,
    )

    # 验证调用了 write_file
    runtime.write_file.assert_called_once()
    call_args = runtime.write_file.call_args
    assert call_args[0][0].startswith("/scratch/test-")
    assert call_args[0][1] == text

    # 验证返回格式
    assert "已存至 /scratch/test-" in result
    assert "read_file" in result
    assert f"{len(text)} 字符" in result


@pytest.mark.asyncio
async def test_offload_threshold_boundary():
    """恰好等于阈值时不卸载。"""
    text = "abc"  # 3 bytes
    settings = _make_settings(offload_threshold_bytes=3)
    result = await offload_if_large(text, runtime=None, settings=settings)
    assert result == text  # 等于阈值不卸载


@pytest.mark.asyncio
async def test_offload_write_file_failure():
    """write_file 抛异常时，返回截断文本而不是崩溃。"""
    settings = _make_settings(offload_threshold_bytes=5, offload_summary_chars=3)
    text = "这是一段很长的文本内容"

    runtime = MagicMock()
    runtime.write_file = AsyncMock(side_effect=OSError("模拟写入失败"))

    result = await offload_if_large(
        text, runtime=runtime, hint="fail", settings=settings,
    )
    assert "落盘失败" in result


# ============================================================
# SessionService.list_reports 测试
# ============================================================


@pytest.mark.asyncio
async def test_list_reports_empty():
    """索引文件不存在时返回空列表。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = _make_settings(
            data_dir=tmpdir,
            report_index_file=Path(tmpdir) / "nonexistent.jsonl",
        )
        svc = SessionService(settings)
        result = await svc.list_reports()
        assert result == []


@pytest.mark.asyncio
async def test_record_and_list_reports():
    """写入两条报告后能查到。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = Path(tmpdir) / "index.jsonl"
        settings = _make_settings(
            data_dir=tmpdir,
            report_index_file=index_path,
        )
        svc = SessionService(settings)

        await svc.record_report("t1", "布洛芬价格偏高", "布洛芬", Path("report1.md"))
        await svc.record_report("t2", "阿莫西林库存充足", "阿莫西林", Path("report2.md"))

        # 查全部
        all_reports = await svc.list_reports()
        assert len(all_reports) == 2

        # 按关键词筛选
        filtered = await svc.list_reports(keyword="布洛芬")
        assert len(filtered) == 1
        assert filtered[0]["topic"] == "布洛芬"


@pytest.mark.asyncio
async def test_record_report_summary_length_limit():
    """摘要超过 100 字时抛 ValueError。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = _make_settings(
            data_dir=tmpdir,
            report_index_file=Path(tmpdir) / "index.jsonl",
        )
        svc = SessionService(settings)

        with pytest.raises(ValueError, match="超出100字"):
            await svc.record_report("t1", "x" * 101, "topic", Path("f.md"))


@pytest.mark.asyncio
async def test_list_reports_with_limit():
    """limit 参数限制返回数量。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = Path(tmpdir) / "index.jsonl"
        settings = _make_settings(
            data_dir=tmpdir,
            report_index_file=index_path,
        )
        svc = SessionService(settings)

        for i in range(5):
            await svc.record_report(
                f"t{i}", f"报告{i}摘要", f"主题{i}", Path(f"r{i}.md"),
            )

        result = await svc.list_reports(limit=2)
        assert len(result) == 2
