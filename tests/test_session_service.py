from app.services.session_service import SessionService


async def test_record_and_list_roundtrip(settings, tmp_path):
    """存进去的报告，查得出来；关键词过滤生效。"""
    svc = SessionService(settings)

    await svc.record_report(
        thread_id="t1",
        topic="布洛芬价格",
        summary="价格上涨 12%",
        path=tmp_path / "a.md",
    )

    assert len(await svc.list_reports()) == 1
    assert len(await svc.list_reports(keyword="布洛芬")) == 1
    assert len(await svc.list_reports(keyword="阿莫西林")) == 0


async def test_list_reports_empty_when_no_index(settings):
    """索引文件不存在时返回空列表，而不是报错。"""
    assert await svc_list(settings) == []


async def svc_list(settings):
    return await SessionService(settings).list_reports()
