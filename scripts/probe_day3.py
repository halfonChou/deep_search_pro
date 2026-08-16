from app.services.session_service import SessionService


async def test_record_and_list_roundtrip(tmp_path, settings):
    settings.report_index_file = tmp_path / "index.jsonl"
    svc = SessionService(settings)

    await svc.record_report("t1", topic="布洛芬价格", summary="价格上涨 12%", path=tmp_path / "a.md")

    assert len(await svc.list_reports()) == 1
    assert len(await svc.list_reports(keyword="布洛芬")) == 1
    assert len(await svc.list_reports(keyword="阿莫西林")) == 0
