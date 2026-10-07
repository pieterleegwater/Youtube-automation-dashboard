from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app import config, db, gemini_client, pipeline, youtube_client

    monkeypatch.setattr(config, "settings", config.Settings(data_dir=tmp_path))
    for mod in (db, pipeline):
        monkeypatch.setattr(mod, "settings", config.settings)
    db.init_db()

    def fake_video(prompt, out_path, clips=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"mp4")
        return out_path

    monkeypatch.setattr(gemini_client, "write_video_plan", lambda s, r: {
        "prompt": "p", "title": f"t {s['name']}", "description": "d", "tags": ["asmr"]})
    monkeypatch.setattr(gemini_client, "generate_video", fake_video)
    monkeypatch.setattr(gemini_client, "propose_strategy", lambda perf: {
        "name": "Nieuw", "theme": "x", "prompt_template": "y", "based_on_strategy_id": perf[0]["strategy_id"],
        "reasoning": "omdat"})
    counter = iter(range(100))
    monkeypatch.setattr(youtube_client, "upload_video", lambda **kw: f"yt{next(counter)}")
    monkeypatch.setattr(youtube_client, "fetch_basic_stats", lambda ids: {i: {"views": 500, "likes": 5, "comments": 1} for i in ids})
    monkeypatch.setattr(youtube_client, "fetch_analytics", lambda ids, s, e: {
        i: {"engagedViews": 100 + 100 * n, "averageViewPercentage": 40.0 + 20 * n} for n, i in enumerate(ids)})
    return pipeline, db


def test_full_cycle(env):
    pipeline, db = env
    vid = pipeline.generate_today()
    assert vid is not None
    assert pipeline.generate_today() is None  # al een video vandaag
    assert pipeline.upload_today() == "yt0"
    assert pipeline.upload_today() is None  # al geüpload vandaag

    # Simuleer een paar oudere uploads per strategie zodat evolve data heeft.
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    with db.connect() as conn:
        for sid in (1, 2, 3, 4):
            for _ in range(3):
                conn.execute("INSERT INTO videos (strategy_id, status, title, youtube_id, created_at, published_at) "
                             "VALUES (?, 'uploaded', 't', ?, ?, ?)", (sid, f"old{sid}{_}", old, old))
    assert pipeline.sync_stats() == 13
    result = pipeline.evolve_strategies()
    assert result["created"] is not None
    with db.connect() as conn:
        overview = pipeline.strategy_overview(conn)
    assert any(s["score"] is not None for s in overview)


def test_upload_generates_when_nothing_ready(env):
    pipeline, _ = env
    assert pipeline.upload_today() == "yt0"
