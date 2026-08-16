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

import pytest

from app.config import Settings
from app.services.session_service import SessionService
from app.tools import _offload as offload_module
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
async def test_offload_outside_graph_context_falls_back_to_truncation():
    """不在 LangGraph 执行上下文里时（StateBackend 拿不到 files 通道），降级成截断文本。

    ★ 断言词从「无法落盘」改成「落盘失败」：_offload 重写后 _truncated() 的 reason
      就是「落盘失败」，原来的措辞在代码里已经不存在了。
    """
    settings = _make_settings(offload_threshold_bytes=10, offload_summary_chars=5)
    text = "这是一段超过阈值的长文本，需要被截断处理"
    result = await offload_if_large(text, runtime=None, settings=settings)
    assert "落盘失败" in result
    assert "已截断" in result


@pytest.mark.asyncio
async def test_offload_large_text_writes_to_state_backend(monkeypatch):
    """超过阈值时经 StateBackend 落盘，返回摘要 + 虚拟路径。

    ★ 落盘机制已从 runtime.write_file 改成模块级 _backend.write：
      deepagents 的 ToolRuntime 根本没有 write_file 方法（见 _offload.py 模块注释），
      所以这里 mock 的是 _backend.write，不再是 runtime。
    """
    settings = _make_settings(offload_threshold_bytes=10, offload_summary_chars=5)
    text = "这是一段超过阈值的长文本，需要被落盘处理并返回摘要"

    written = {}

    class _OkResult:
        error = None

    def _fake_write(path, content):
        written["path"] = path
        written["content"] = content
        return _OkResult()

    monkeypatch.setattr(offload_module._backend, "write", _fake_write)

    result = await offload_if_large(
        text, runtime=None, hint="test", settings=settings,
    )

    # 验证写进了 /scratch，且写的是全文
    assert written["path"].startswith("/scratch/test-")
    assert written["content"] == text

    # 验证返回格式
    assert "已存至虚拟文件 /scratch/test-" in result
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
async def test_offload_write_file_failure(monkeypatch):
    """backend.write 抛异常时，返回截断文本而不是崩溃。"""
    settings = _make_settings(offload_threshold_bytes=5, offload_summary_chars=3)
    text = "这是一段很长的文本内容"

    def _boom(path, content):
        raise OSError("模拟写入失败")

    monkeypatch.setattr(offload_module._backend, "write", _boom)

    result = await offload_if_large(
        text, runtime=None, hint="fail", settings=settings,
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

        # ★ 签名是 record_report(thread_id, topic, summary, path)——原来这里 topic/summary
        #   传反了，所以 filtered[0]["topic"] 取到的是摘要。
        await svc.record_report("t1", "布洛芬", "布洛芬价格偏高", Path("report1.md"))
        await svc.record_report("t2", "阿莫西林", "阿莫西林库存充足", Path("report2.md"))

        # 查全部
        all_reports = await svc.list_reports()
        assert len(all_reports) == 2

        # 按关键词筛选
        filtered = await svc.list_reports(keyword="布洛芬")
        assert len(filtered) == 1
        assert filtered[0]["topic"] == "布洛芬"


@pytest.mark.asyncio
async def test_record_report_summary_truncated_not_raised():
    """摘要超过 100 字时**截断**，不抛 ValueError。

    ★ 行为变更（见 session_service.record_report 注释）：原来超长直接 raise，
      但那时报告文件已经写到磁盘上了——用户拿得到报告、模型却收到"失败"，
      于是白重试一轮。摘要长一点不是错误，截断即可。
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = _make_settings(
            data_dir=tmpdir,
            report_index_file=Path(tmpdir) / "index.jsonl",
        )
        svc = SessionService(settings)

        await svc.record_report("t1", "topic", "x" * 150, Path("f.md"))

        reports = await svc.list_reports()
        assert len(reports) == 1
        assert reports[0]["summary"] == "x" * 100   # 截到 _SUMMARY_MAX


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
