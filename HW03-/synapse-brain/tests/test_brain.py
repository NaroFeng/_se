"""Pytest cases for the SynapseBrain pipeline."""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import compiler
import database as db


@pytest.fixture()
def memdb(tmp_path):
    path = str(tmp_path / "test.db")
    db.init_db(path)
    return path


def test_node_crud_and_boost(memdb):
    db.upsert_node({"id": "python", "label": "Python", "category": "skill",
                    "weight": 2.0, "summary": "lang"}, db_path=memdb)
    got = db.get_node("python", db_path=memdb)
    assert got["label"] == "Python"

    boosted = db.boost_node("python", 0.5, db_path=memdb)
    assert boosted["weight"] == pytest.approx(2.5)

    # weight clamps at 10.0
    db.boost_node("python", 100.0, db_path=memdb)
    assert db.get_node("python", db_path=memdb)["weight"] == pytest.approx(10.0)

    assert db.delete_node("python", db_path=memdb) is True
    assert db.get_node("python", db_path=memdb) is None


def test_edge_crud_and_cascade(memdb):
    db.upsert_node({"id": "python", "label": "Python"}, db_path=memdb)
    db.upsert_node({"id": "fastapi", "label": "FastAPI"}, db_path=memdb)
    e = db.add_edge("fastapi", "python", "depends_on", db_path=memdb)
    assert e["relation"] == "depends_on"

    with pytest.raises(ValueError):
        db.add_edge("fastapi", "ghost", "depends_on", db_path=memdb)

    db.delete_node("python", db_path=memdb)
    assert db.get_edges(db_path=memdb) == []


def test_compile_prompt_selects_top_weights(memdb):
    for i in range(5):
        db.upsert_node({"id": f"n{i}", "label": f"N{i}", "weight": float(i + 1),
                        "summary": f"s{i}"}, db_path=memdb)
    nodes, edges = db.get_nodes(db_path=memdb), db.get_edges(db_path=memdb)
    out = compiler.compile_prompt(nodes, edges, limit=2)
    assert out["count"] == 2
    assert out["node_ids"] == ["n4", "n3"]  # highest weights first
    assert "```brain-update" in out["prompt"]
    assert '"boost_nodes"' in out["prompt"]


def test_compile_prompt_focus_pins_neighbours(memdb):
    db.upsert_node({"id": "a", "label": "A", "weight": 1.0}, db_path=memdb)
    db.upsert_node({"id": "b", "label": "B", "weight": 1.0}, db_path=memdb)
    db.upsert_node({"id": "strong", "label": "S", "weight": 9.0}, db_path=memdb)
    db.add_edge("a", "b", "related_to", db_path=memdb)
    nodes, edges = db.get_nodes(db_path=memdb), db.get_edges(db_path=memdb)
    out = compiler.compile_prompt(nodes, edges, focus_topic="a", limit=2)
    assert out["node_ids"][0] == "a"
    assert "b" in out["node_ids"]  # neighbour pinned above stronger outsider


def test_ingest_valid_block(memdb):
    db.upsert_node({"id": "python", "label": "Python", "weight": 1.0}, db_path=memdb)
    text = """Nice work!
```brain-update
{"new_nodes": [{"id": "docker", "label": "Docker", "summary": "containers", "weight": 1.5}],
 "boost_nodes": ["python"],
 "new_edges": [{"source": "docker", "target": "python", "relation": "relates_to"}]}
```
"""
    summary = compiler.apply_ingest(
        text,
        upsert_node_fn=lambda n: db.upsert_node(n, db_path=memdb),
        boost_node_fn=lambda i, a=0.5: db.boost_node(i, a, db_path=memdb),
        add_edge_fn=lambda s, t, r="related_to": db.add_edge(s, t, r, db_path=memdb),
    )
    assert summary["blocks_found"] == 1
    assert summary["new_nodes"] == ["docker"]
    assert summary["boosted_nodes"] == ["python"]
    assert db.get_node("docker", db_path=memdb)["summary"] == "containers"
    assert db.get_node("python", db_path=memdb)["weight"] == pytest.approx(1.5)


def test_ingest_malformed_and_unknown_boost(memdb):
    text = """```brain-update
{not valid json!!!
```
```brain-update
{"boost_nodes": ["ghost-node"], "new_nodes": [], "new_edges": []}
```
"""
    summary = compiler.apply_ingest(
        text,
        upsert_node_fn=lambda n: db.upsert_node(n, db_path=memdb),
        boost_node_fn=lambda i, a=0.5: db.boost_node(i, a, db_path=memdb),
        add_edge_fn=lambda s, t, r="related_to": db.add_edge(s, t, r, db_path=memdb),
    )
    assert summary["blocks_found"] == 1  # only the parseable block counts
    assert summary["errors"], "expected errors for malformed block + ghost boost"


def test_api_endpoints_with_isolated_db(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    isolated = str(tmp_path / "api.db")
    monkeypatch.setenv("SYNAPSE_DB", isolated)
    import importlib
    import main as app_mod

    importlib.reload(app_mod)
    client = TestClient(app_mod.app)

    r = client.post("/api/nodes", json={"id": "python", "label": "Python"})
    assert r.status_code == 201
    r = client.post("/api/nodes", json={"id": "fastapi", "label": "FastAPI"})
    assert r.status_code == 201
    r = client.post("/api/edges", json={"source": "fastapi", "target": "python",
                                        "relation": "depends_on"})
    assert r.status_code == 201
    r = client.post("/api/nodes/python/boost")
    assert r.status_code == 200 and r.json()["weight"] > 1.0
    r = client.post("/api/compile-prompt", json={"limit": 5})
    assert r.status_code == 200 and "brain-update" in r.json()["prompt"]
    ingest_text = "```brain-update\n" + '{"new_nodes": [{"id": "k8s", "label": "K8s"}]}\n```'
    r = client.post("/api/ingest", json={"text": ingest_text})
    assert r.status_code == 200 and "k8s" in r.json()["new_nodes"]
    r = client.get("/api/graph")
    assert any(n["id"] == "k8s" for n in r.json()["nodes"])


def test_local_chat_memory_writeback(tmp_path, monkeypatch):
    """Fake Ollama: chat reply + extraction block both flow into the graph."""
    from fastapi.testclient import TestClient

    isolated = str(tmp_path / "chat.db")
    monkeypatch.setenv("SYNAPSE_DB", isolated)
    import importlib
    import main as app_mod

    importlib.reload(app_mod)
    calls = []

    async def fake_generate(prompt, timeout=180.0, system=None, **kwargs):
        calls.append((prompt, system))
        if "你是記憶萃取器" in prompt:  # extraction round（用提示詞開頭判斷，
            # 不要綁 "brain-update" 字樣——萃取已改走 format="json"，提示詞裡
            # 已經不再出現那個字串了）
            return ({"response": "```brain-update\n"
                    '{"new_nodes": [{"id": "docker", "label": "Docker", '
                    '"summary": "containers"}], "boost_nodes": [], '
                    '"new_edges": []}\n```', "model": "fake"}, None)
        return ({"response": "容器很好用", "model": "fake"}, None)

    monkeypatch.setattr(app_mod, "_ollama_generate", fake_generate)
    client = TestClient(app_mod.app)

    r = client.post("/api/local-chat", json={"message": "聊聊容器", "remember": True})
    assert r.status_code == 200
    body = r.json()
    assert body["mock"] is False
    assert body["response"] == "容器很好用"
    assert body["memory"]["new_nodes"] == ["docker"]
    assert len(calls) == 2  # 一次對話 + 一次萃取
    assert any("繁體中文" in (s or "") for _, s in calls)  # 對話有帶中文系統指令
    assert any("Python" in (s or "") for _, s in calls)  # 對話有帶入記憶節點

    # remember=False 只打一次，不寫回
    calls.clear()
    r = client.post("/api/local-chat", json={"message": "嗨", "remember": False})
    assert r.json()["memory"] is None
    assert len(calls) == 1

    # Ollama 連不上 → 示範回覆，且不做記憶寫回
    async def fake_down(prompt, timeout=180.0, system=None, **kwargs):
        return None, {"kind": "unreachable", "detail": "down"}

    monkeypatch.setattr(app_mod, "_ollama_generate", fake_down)
    r = client.post("/api/local-chat", json={"message": "嗨", "remember": True})
    assert r.json()["mock"] is True
    assert r.json()["memory"] is None


def test_local_chat_model_missing_message(tmp_path, monkeypatch):
    """Ollama 活著但模型還沒下好（404）→ 訊息要講清楚，不要謊稱連不上。"""
    from fastapi.testclient import TestClient

    isolated = str(tmp_path / "missing.db")
    monkeypatch.setenv("SYNAPSE_DB", isolated)
    import importlib
    import main as app_mod

    importlib.reload(app_mod)

    async def fake_missing(prompt, timeout=180.0, system=None, **kwargs):
        return None, {"kind": "model_missing",
                      "detail": "model 'llama3:8b' not found, try pulling it first"}

    monkeypatch.setattr(app_mod, "_ollama_generate", fake_missing)
    client = TestClient(app_mod.app)
    r = client.post("/api/local-chat", json={"message": "嗨", "remember": True})
    body = r.json()
    assert body["mock"] is True
    assert "模型還沒準備好" in body["response"]
    assert "ollama pull" in body["response"]
    assert "連不上" not in body["response"]
    assert body["memory"] is None


def _make_stream_client(app_mod, monkeypatch, *, status=200, lines=(), body=b"", capture=None):
    """用假的 httpx.AsyncClient 餵 Ollama 串流（NDJSON 行）。capture 會收到送出的 json。"""

    class FakeStreamResp:
        status_code = status

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aread(self):
            return body

        async def aiter_lines(self):
            for ln in lines:
                yield ln

    class FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def stream(self, *a, **k):
            if capture is not None:
                capture.update(k)
            return FakeStreamResp()

    monkeypatch.setattr(app_mod.httpx, "AsyncClient", FakeAsyncClient)


def _sse_events(text):
    import json as jsonlib

    return [
        jsonlib.loads(chunk[6:])
        for chunk in text.split("\n\n")
        if chunk.startswith("data:")
    ]


def test_local_chat_stream_tokens_and_memory(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import json as jsonlib

    isolated = str(tmp_path / "stream.db")
    monkeypatch.setenv("SYNAPSE_DB", isolated)
    import importlib
    import main as app_mod

    importlib.reload(app_mod)
    sent = {}
    _make_stream_client(
        app_mod, monkeypatch, status=200, capture=sent,
        lines=[
            jsonlib.dumps({"response": "你好", "done": False}),
            jsonlib.dumps({"response": "呀", "done": True}),
        ],
    )

    async def fake_extract(prompt, timeout=180.0, system=None, **kwargs):
        return ({"response": '```brain-update\n{"new_nodes": [{"id": "rust", "label": "Rust"}]}\n```'}, None)

    monkeypatch.setattr(app_mod, "_ollama_generate", fake_extract)
    client = TestClient(app_mod.app)
    r = client.post("/api/local-chat-stream", json={"message": "嗨", "remember": True})
    assert r.status_code == 200
    events = _sse_events(r.text)
    assert "".join(e.get("token", "") for e in events) == "你好呀"
    final = next(e for e in events if e.get("done"))
    assert final["mock"] is False
    assert final["memory"]["new_nodes"] == ["rust"]
    # 回歸：串流送出的 system 必須含記憶（含繁中規則），否則等於沒注入
    assert "繁中回覆" in sent["json"]["system"]
    assert "必須遵守的規則" in sent["json"]["system"]
    assert sent["json"]["prompt"].endswith("（請用繁體中文回答。）")
    assert sent["json"]["options"]["temperature"] == 0.3


def test_local_chat_stream_model_missing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    isolated = str(tmp_path / "stream404.db")
    monkeypatch.setenv("SYNAPSE_DB", isolated)
    import importlib
    import main as app_mod

    importlib.reload(app_mod)
    _make_stream_client(
        app_mod, monkeypatch, status=404,
        body=b'{"error": "model \'llama3:8b\' not found, try pulling it first"}',
    )
    client = TestClient(app_mod.app)
    r = client.post("/api/local-chat-stream", json={"message": "嗨", "remember": True})
    events = _sse_events(r.text)
    assert "模型還沒準備好" in "".join(e.get("token", "") for e in events)
    final = next(e for e in events if e.get("done"))
    assert final["mock"] is True
    assert final["memory"] is None


def test_seed_demo_idempotent_and_linked(tmp_path):
    path = str(tmp_path / "demo.db")
    db.init_db(path)
    c1 = db.seed_demo(path)
    c2 = db.seed_demo(path)  # 重跑冪等：數量一致、無重複
    assert c1 == c2
    assert c1["nodes"] >= 10 and c1["edges"] >= 10
    g = db.get_graph(db_path=path)
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])
    assert {"topic", "skill", "persona", "rule"} <= {n["category"] for n in g["nodes"]}


def test_seed_demo_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SYNAPSE_DB", str(tmp_path / "seedapi.db"))
    import importlib
    import main as app_mod

    importlib.reload(app_mod)
    client = TestClient(app_mod.app)
    r = client.post("/api/seed-demo")
    assert r.status_code == 200
    body = r.json()
    assert body["seeded"] is True
    assert len(body["graph"]["nodes"]) >= 10


def test_extraction_prompt_constrains_relations():
    import main as app_mod

    p = app_mod._build_extraction_prompt("嗨", "你好", ["python"])
    assert "relates_to" in p
    assert "不要自創" in p
    # 圖譜節點要和介面一致，一律繁中，否則會混進整串英文節點
    assert "繁體中文" in p


def test_lang_suffix_appended():
    import main as app_mod

    assert app_mod._with_lang_suffix("hi").endswith("（請用繁體中文回答。）")


def test_unload_after_chat_flag(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SYNAPSE_DB", str(tmp_path / "unload.db"))
    monkeypatch.setenv("OLLAMA_UNLOAD_AFTER_CHAT", "1")
    import importlib
    import main as app_mod

    importlib.reload(app_mod)
    calls = {"chat": 0, "unload": 0}

    async def fake_gen(prompt, timeout=180.0, system=None, **kwargs):
        calls["chat"] += 1
        return ({"response": "好", "model": "fake"}, None)

    async def fake_unload():
        calls["unload"] += 1

    monkeypatch.setattr(app_mod, "_ollama_generate", fake_gen)
    monkeypatch.setattr(app_mod, "_ollama_unload", fake_unload)
    client = TestClient(app_mod.app)
    r = client.post("/api/local-chat", json={"message": "嗨", "remember": False})
    assert r.status_code == 200
    assert calls == {"chat": 1, "unload": 1}
    # 旗標關閉就不卸載
    monkeypatch.setenv("OLLAMA_UNLOAD_AFTER_CHAT", "0")
    r = client.post("/api/local-chat", json={"message": "嗨", "remember": False})
    assert calls == {"chat": 2, "unload": 1}


def test_busy_timeout_set(tmp_path):
    path = str(tmp_path / "busy.db")
    db.init_db(path)
    conn = db.get_connection(path)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        conn.close()


def test_chat_memory_context_includes_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNAPSE_DB", str(tmp_path / "ctx.db"))
    db.init_db()
    db.upsert_node({"id": "zh-reply", "label": "繁中回覆", "category": "rule",
                    "weight": 2.4, "summary": "一律用繁體中文"})
    db.upsert_node({"id": "python", "label": "Python", "category": "skill",
                    "weight": 2.5, "summary": "主力語言"})
    import main as app_mod

    ctx = app_mod._build_memory_context()
    assert "Python" in ctx and "主力語言" in ctx
    assert "必須遵守的規則" in ctx and "繁中回覆" in ctx


def test_probe_ollama_unreachable_without_server(monkeypatch):
    import main as app_mod

    class BoomClient:
        def __init__(self, *a, **k):
            raise ConnectionError("down")

    monkeypatch.setattr(app_mod.httpx, "Client", BoomClient)
    assert app_mod.probe_ollama() == {"reachable": False, "version": None, "models": []}


def test_ensure_ollama_skipped_without_binary(monkeypatch):
    import main as app_mod

    monkeypatch.setattr(app_mod.shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(
        app_mod, "probe_ollama",
        lambda timeout=2.0: {"reachable": False, "version": None, "models": []},
    )
    st = app_mod.ensure_ollama()
    assert st["started"] is False
    assert "binary" in st["skipped"]
    assert app_mod._ollama_proc is None  # 沒亂開行程


# ---------- Event-driven decay ----------

def test_decay_only_hits_topic_and_skill(memdb):
    for nid, cat, w in [
        ("rag", "topic", 2.0),
        ("python", "skill", 2.5),
        ("ai-assistant", "persona", 3.0),
        ("zh-reply", "rule", 2.4),
    ]:
        db.upsert_node({"id": nid, "label": nid, "category": cat, "weight": w},
                       db_path=memdb)

    touched = db.decay_others(exclude_ids=["rag"], db_path=memdb)
    assert touched == 1  # 只有 python 被扣（rag 被排除，persona/rule 不參與）

    assert db.get_node("rag", db_path=memdb)["weight"] == pytest.approx(2.0)  # 本次被碰過
    assert db.get_node("python", db_path=memdb)["weight"] == pytest.approx(2.45)
    assert db.get_node("ai-assistant", db_path=memdb)["weight"] == pytest.approx(3.0)
    assert db.get_node("zh-reply", db_path=memdb)["weight"] == pytest.approx(2.4)


def test_decay_repeats_and_never_below_floor(memdb):
    db.upsert_node({"id": "streaming", "label": "S", "category": "topic",
                    "weight": 1.2}, db_path=memdb)
    db.upsert_node({"id": "docker", "label": "D", "category": "skill",
                    "weight": 1.0}, db_path=memdb)

    # 連續在其他節點被更新 3 次 → 1.2 * 0.98^3
    for _ in range(3):
        db.upsert_node({"id": "fresh", "label": "F", "category": "topic",
                        "weight": 1.0}, db_path=memdb)
        db.decay_others(exclude_ids=["fresh"], db_path=memdb)
    assert db.get_node("streaming", db_path=memdb)["weight"] == pytest.approx(
        round(1.2 * 0.98 ** 3, 3)
    )

    # 推到地板：0.1 不會再往下掉（0.12 大約 10 次才會碰到地板，這裡給足餘裕）
    db.upsert_node({"id": "streaming", "label": "S", "category": "topic",
                    "weight": 0.12}, db_path=memdb)
    for _ in range(30):
        db.decay_others(exclude_ids=["fresh"], db_path=memdb)
    assert db.get_node("streaming", db_path=memdb)["weight"] == pytest.approx(0.1)


def test_ingest_calls_decay_once_with_touched_ids(memdb):
    db.upsert_node({"id": "python", "label": "Python", "category": "skill",
                    "weight": 1.0}, db_path=memdb)
    db.upsert_node({"id": "rag", "label": "RAG", "category": "topic",
                    "weight": 2.0}, db_path=memdb)
    calls = []

    def fake_decay(ids):
        calls.append(list(ids))
        return db.decay_others(exclude_ids=ids, db_path=memdb)

    text = """```brain-update
{"new_nodes": [{"id": "docker", "label": "Docker", "category": "skill", "weight": 1.5}],
 "boost_nodes": ["python"], "new_edges": []}
```"""
    summary = compiler.apply_ingest(
        text,
        upsert_node_fn=lambda n: db.upsert_node(n, db_path=memdb),
        boost_node_fn=lambda i, a=0.5: db.boost_node(i, a, db_path=memdb),
        add_edge_fn=lambda s, t, r="related_to": db.add_edge(s, t, r, db_path=memdb),
        decay_fn=fake_decay,
    )
    assert len(calls) == 1, "一輪 ingest 只衰減一次，不是每個 boost 一次"
    assert set(calls[0]) == {"docker", "python"}
    assert summary["decayed_nodes"] == 1  # 只有 rag 淡出
    assert db.get_node("rag", db_path=memdb)["weight"] == pytest.approx(1.96)


def test_resolve_port_skips_occupied(monkeypatch):
    import socket as s

    import main as app_mod

    monkeypatch.delenv("SYNAPSE_PORT", raising=False)
    # 假裝 8800、8801 都被占著
    monkeypatch.setattr(
        app_mod, "_port_is_free", lambda port, host=app_mod.HOST: port >= 8802
    )
    assert app_mod.resolve_port() == 8802

    monkeypatch.setenv("SYNAPSE_PORT", "8900")
    assert app_mod.resolve_port() == 8900  # 明確指定就從那裡起跳

    monkeypatch.setenv("SYNAPSE_PORT", "not-a-number")
    assert app_mod.resolve_port() == 8802  # 壞值退回預設掃描

    monkeypatch.setattr(
        app_mod, "_port_is_free", lambda port, host=app_mod.HOST: False
    )
    with pytest.raises(SystemExit):
        app_mod.resolve_port()


def test_port_file_roundtrip(tmp_path, monkeypatch):
    import main as app_mod

    fake = tmp_path / ".port"
    monkeypatch.setattr(app_mod, "PORT_FILE", fake)
    app_mod.write_port_file(8803)
    assert fake.read_text(encoding="utf-8") == "8803"
    app_mod.clear_port_file()
    assert not fake.exists()
    app_mod.clear_port_file()  # 再清一次不該拋錯


# ---------- Stream resilience ----------

def _collect_sse(chunks):
    """把 SSE 位元組串流解析成事件列表（忽略 ': keepalive' 註解）。"""
    import json as jsonlib

    events = []
    for block in chunks.split("\n\n"):
        block = block.strip()
        if not block or not block.startswith("data:"):
            continue
        events.append(jsonlib.loads(block[5:]))
    return events


def test_stream_survives_extraction_failure(tmp_path, monkeypatch):
    """記憶萃取整個爆掉時，串流仍必須照常送出 done，前端才不會掉連線。"""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SYNAPSE_DB", str(tmp_path / "streamfail.db"))
    import importlib
    import main as app_mod

    importlib.reload(app_mod)
    monkeypatch.setattr(app_mod, "OLLAMA_MODEL", "fake-model")

    class FakeStream:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aiter_lines(self):
            import json as jsonlib
            yield jsonlib.dumps({"response": "哲學滿好的。"})
            yield jsonlib.dumps({"done": True})

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def stream(self, *a, **k):
            return FakeStream()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise RuntimeError("extraction exploded")

    monkeypatch.setattr(app_mod.httpx, "AsyncClient", FakeClient)

    client = TestClient(app_mod.app)
    with client.stream(
        "POST", "/api/local-chat-stream", json={"message": "我喜歡哲學", "remember": True}
    ) as resp:
        assert resp.status_code == 200
        raw = "".join(resp.iter_text())

    events = _collect_sse(raw)
    tokens = [e["token"] for e in events if "token" in e]
    assert "哲學滿好的。" in "".join(tokens), "萃取爆掉不該吃掉已經生出來的回覆"
    done = [e for e in events if e.get("done")]
    assert done, "萃取失敗後仍然必須送出 done，否則前端會判定串流中斷"
    # 錯誤訊息內容不重要，重要的是它有回報、而且串流沒有被弄斷
    assert "記憶寫回" in done[-1]["memory"]["error"]


def test_stream_emits_keepalive_during_extraction(tmp_path, monkeypatch):
    """萃取期間要送 data 忙碌事件維持連線，並讓前端有東西可以顯示。"""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SYNAPSE_DB", str(tmp_path / "keepalive.db"))
    monkeypatch.setenv("EXTRACT_KEEPALIVE", "0.01")
    import importlib
    import main as app_mod

    importlib.reload(app_mod)

    class FakeStream:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def aiter_lines(self):
            import json as jsonlib
            yield jsonlib.dumps({"response": "嗨"})
            yield jsonlib.dumps({"done": True})

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def stream(self, *a, **k):
            return FakeStream()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            import asyncio
            await asyncio.sleep(0.08)
            return ({"response": "```brain-update\n{}\n```", "model": "m"}, None)

    monkeypatch.setattr(app_mod.httpx, "AsyncClient", FakeClient)

    client = TestClient(app_mod.app)
    with client.stream(
        "POST", "/api/local-chat-stream", json={"message": "嗨", "remember": True}
    ) as resp:
        raw = "".join(resp.iter_text())
        assert resp.headers.get("cache-control") == "no-cache"

    events = _collect_sse(raw)
    busy = [e for e in events if e.get("busy")]
    assert busy, "萃取期間應該送忙碌事件，避免長靜默被當成斷線"
    assert all(e.get("token") is None and e.get("done") is None for e in busy)
    assert events[-1].get("done") is True


def test_extract_memory_never_raises(tmp_path, monkeypatch):
    """_extract_memory 的契約：任何情況都回傳 dict，不往外丟例外。"""
    monkeypatch.setenv("SYNAPSE_DB", str(tmp_path / "never.db"))
    import importlib
    import main as app_mod

    importlib.reload(app_mod)
    monkeypatch.setattr(app_mod, "db", SimpleNamespace(get_nodes=lambda: []))

    async def boom(*a, **k):
        raise RuntimeError("ollama on fire")

    monkeypatch.setattr(app_mod, "_ollama_generate", boom)
    import asyncio

    out = asyncio.run(app_mod._extract_memory("a", "b"))
    assert "error" in out and "記憶寫回" in out["error"]


def test_ingest_tolerates_models_that_drop_the_fence_tag(memdb):
    """實測 llama3:8b 會把 ```brain-update 標成 ``` 甚至加英文前言。

    只認標籤的話記憶寫回會安靜地變成 0 筆，所以解析器必須靠內容判斷。
    """
    raw = """Here is the brain update code block:

```
{
    "new_nodes": [
        {"id": "philosophy", "label": "哲學", "weight": 0.8}
    ],
    "boost_nodes": ["ai-assistant"],
    "new_edges": []
}
```"""
    assert compiler.extract_brain_updates(raw) == [{
        "new_nodes": [{"id": "philosophy", "label": "哲學", "weight": 0.8}],
        "boost_nodes": ["ai-assistant"],
        "new_edges": [],
    }]

    db.upsert_node({"id": "ai-assistant", "label": "AI", "category": "persona",
                    "weight": 1.0}, db_path=memdb)
    summary = compiler.apply_ingest(
        raw,
        upsert_node_fn=lambda n: db.upsert_node(n, db_path=memdb),
        boost_node_fn=lambda i, a=0.5: db.boost_node(i, a, db_path=memdb),
        add_edge_fn=lambda s, t, r="related_to": db.add_edge(s, t, r, db_path=memdb),
    )
    assert summary["blocks_found"] == 1
    assert summary["new_nodes"] == ["philosophy"]
    assert summary["boosted_nodes"] == ["ai-assistant"]
    assert summary["errors"] == [], "能認出來就不該報錯"


def test_ingest_ignores_unrelated_code_fences(memdb):
    """普通的程式碼區塊不能被誤認成 brain-update。"""
    raw = """這段程式碼示範如何用 Python：
```python
x = {"new_nodes": "not really a payload"}
print(x)
```"""
    assert compiler.extract_brain_updates(raw) == []


def test_ingest_accepts_bare_json_from_json_mode():
    """Ollama format="json" 模式回傳的是裸 JSON、沒有任何 fence。"""
    raw = '{"new_nodes": [{"id": "books", "label": "閱讀"}], "boost_nodes": [], "new_edges": []}'
    assert compiler.extract_brain_updates(raw) == [{
        "new_nodes": [{"id": "books", "label": "閱讀"}],
        "boost_nodes": [],
        "new_edges": [],
    }]


def test_ingest_accepts_bare_json_with_preamble_and_no_duplicates():
    """JSON 模式偶爾還是會加前言；而且同一份不能被重複吃兩次。"""
    raw = 'Sure! Here is the update:\n\n{"new_nodes": [], "boost_nodes": ["python"], "new_edges": []}\n\nHope that helps!'
    payloads = compiler.extract_brain_updates(raw)
    assert len(payloads) == 1, f"同一份 payload 不該被重複解析：{payloads}"
    assert payloads[0]["boost_nodes"] == ["python"]


def test_bare_and_fenced_forms_do_not_double_count():
    """同一份 payload 同時以 fenced 與整段出現時也只算一次。"""
    body = '{"new_nodes": [], "boost_nodes": ["python"], "new_edges": []}'
    raw = f"前言\n\n```\n{body}\n```\n"
    assert len(compiler.extract_brain_updates(raw)) == 1


def test_json_mode_is_requested_for_extraction(tmp_path, monkeypatch):
    """萃取呼叫必須帶 format="json"，否則模型又會吐 Markdown。"""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SYNAPSE_DB", str(tmp_path / "jsonmode.db"))
    import importlib
    import main as app_mod

    importlib.reload(app_mod)
    captured = {}

    async def fake_gen(prompt, timeout=180.0, system=None, **kwargs):
        captured.update(kwargs)
        return ({"response": '{"new_nodes": [], "boost_nodes": [], "new_edges": []}',
                 "model": "m"}, None)

    monkeypatch.setattr(app_mod, "_ollama_generate", fake_gen)
    monkeypatch.setattr(app_mod.db, "get_nodes", lambda *a, **k: [])
    import asyncio

    out = asyncio.run(app_mod._extract_memory("嗨", "你好"))
    assert captured.get("json_mode") is True
    assert "num_predict" in captured.get("options_override", {})
    assert out["blocks_found"] == 1


def test_raw_output_logged_when_nothing_parsed(tmp_path, monkeypatch, capsys):
    """解析不到時必須把模型原文印出來，否則這種故障查不下去。"""
    monkeypatch.setenv("SYNAPSE_DB", str(tmp_path / "raw.db"))
    import importlib
    import main as app_mod

    importlib.reload(app_mod)

    async def fake_gen(prompt, timeout=180.0, system=None, **kwargs):
        return ({"response": "I refuse to comply. Sorry!"}, None)

    monkeypatch.setattr(app_mod, "_ollama_generate", fake_gen)
    monkeypatch.setattr(app_mod.db, "get_nodes", lambda *a, **k: [])
    import asyncio

    out = asyncio.run(app_mod._extract_memory("嗨", "你好"))
    assert out["blocks_found"] == 0
    printed = capsys.readouterr().out
    assert "解析不到 brain-update" in printed
    assert "I refuse to comply" in printed, "要把模型原文印出來才查得下去"


def test_dump_raw_truncates_but_says_so():
    import main as app_mod

    assert app_mod._dump_raw("") == "（空字串）"
    short = app_mod._dump_raw("abc")
    assert short == "abc"
    long = app_mod._dump_raw("x" * 5000)
    assert "已截斷" in long and "5000" in long


def test_timeout_is_not_misreported_as_unreachable(monkeypatch):
    """逾時的 str() 是空字串，混進 unreachable 會給出「請開 Ollama」的錯建議。"""
    import importlib
    import httpx
    import main as app_mod

    importlib.reload(app_mod)

    class TimingOutClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(app_mod.httpx, "AsyncClient", TimingOutClient)
    import asyncio

    data, err = asyncio.run(app_mod._ollama_generate("hi", timeout=12.0))
    assert data is None
    assert err["kind"] == "timeout", f"逾時不該被分類成 {err['kind']!r}"
    assert err["detail"] and "12" in err["detail"], "逾時必須留下可診斷的 detail"

    text = app_mod._mock_text(err, "嗨")
    assert "逾時" in text
    assert "連不上 Ollama" not in text, "逾時時不該叫人去開 Ollama"


def test_unreachable_keeps_exception_type(monkeypatch):
    import importlib
    import httpx
    import main as app_mod

    importlib.reload(app_mod)

    class DeadClient:
        def __init__(self, *a, **k):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(app_mod.httpx, "AsyncClient", DeadClient)
    import asyncio

    _, err = asyncio.run(app_mod._ollama_generate("hi"))
    assert err["kind"] == "unreachable"
    assert "ConnectError" in err["detail"], "連不上時要留下例外型別才方便診斷"
