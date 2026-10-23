"""SynapseBrain API server (FastAPI). Run with `python main.py`."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import compiler as compiler_mod
import database as db

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# ---- Server binding -------------------------------------------------------
# 起始 port 來自 $env:SYNAPSE_PORT（預設 8800）。被占用就往後遞增探測，
# 避免跟同機器的 Ollama / Docker / WSL 服務打架；實際綁到的 port 寫進 .port，
# 讓腳本與自動化測試可以讀取，不必靠猜。
HOST = "127.0.0.1"
DEFAULT_PORT = 8800
PORT_SCAN_COUNT = 21  # 8800 ~ 8820
PORT_FILE = BASE_DIR / ".port"


def _port_is_free(port: int, host: str = HOST) -> bool:
    """True if nothing is currently listening on host:port.

    Deliberately no SO_REUSEADDR: on Windows that flag lets a second socket
    bind an already-bound port, which would make this probe lie.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, int(port)))
        except OSError:
            return False
    return True


def resolve_port(host: str = HOST) -> int:
    """起始 port 起跳逐個試，回傳第一個空閒的 port。"""
    raw = os.environ.get("SYNAPSE_PORT", "").strip()
    try:
        start = int(raw) if raw else DEFAULT_PORT
    except ValueError:
        print(f"[synapse] SYNAPSE_PORT={raw!r} 不是數字，改用預設 {DEFAULT_PORT}。")
        start = DEFAULT_PORT
    # 確保整個掃描區間都還在合法範圍內
    start = max(1, min(start, 65535 - (PORT_SCAN_COUNT - 1)))
    for port in range(start, start + PORT_SCAN_COUNT):
        if _port_is_free(port, host):
            if port != start:
                print(f"[synapse] port {start} 已被占用，自動改用 {port}。")
            return port
    raise SystemExit(
        f"[synapse] {start}~{start + PORT_SCAN_COUNT - 1} 全部被占用，"
        f"請用 $env:SYNAPSE_PORT 指定其他 port。"
    )


def write_port_file(port: int) -> None:
    try:
        PORT_FILE.write_text(str(port), encoding="utf-8")
    except OSError as exc:
        print(f"[synapse] 無法寫入 {PORT_FILE.name}：{exc}")


def clear_port_file() -> None:
    try:
        if PORT_FILE.exists():
            PORT_FILE.unlink()
    except OSError:
        pass

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3:8b")
# 1=啟動時若 Ollama 沒跑就自動幫你開；0=完全不碰，只用示範回覆
OLLAMA_AUTOSTART = os.environ.get("OLLAMA_AUTOSTART", "1") == "1"
# 1=模型沒下載就背景自動 pull（會吃流量+等很久）；預設只提醒指令
OLLAMA_AUTOPULL = os.environ.get("OLLAMA_AUTOPULL", "0") == "1"


def _unload_after_chat() -> bool:
    # 每次讀 env：測試和臨時切換不用重開 server
    return os.environ.get("OLLAMA_UNLOAD_AFTER_CHAT", "0") == "1"


async def _ollama_unload() -> None:
    """用完即走：把模型從記憶體卸載（server 繼續跑著）。保證不拋錯。"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": "hi",
                      "stream": False, "keep_alive": 0},
            )
    except Exception:
        pass
# 預設回覆語言/人設，可用 OLLAMA_SYSTEM 整段覆寫（例如想切英文）
CHAT_SYSTEM = os.environ.get(
    "OLLAMA_SYSTEM",
    "你是 SynapseBrain，使用者的本地記憶小幫手。"
    "最重要的規則：全程使用繁體中文（台灣用語）回答，絕對不要使用英文。"
    "語氣親切簡潔。",
)


def _ollama_options() -> dict[str, Any]:
    try:
        t = float(os.environ.get("OLLAMA_TEMPERATURE", "0.3"))
    except ValueError:
        t = 0.3
    return {"temperature": max(0.0, min(2.0, t))}


def _with_lang_suffix(message: str) -> str:
    # 小模型容易無視 system：在使用者訊息尾再補一句中文要求（除非人設已切英文）
    if "中文" in CHAT_SYSTEM:
        return message + "\n\n（請用繁體中文回答。）"
    return message
# 每次對話自動帶入幾則權重最高的記憶（可在編譯頁籤預覽同樣內容）
CHAT_MEMORY_LIMIT = int(os.environ.get("CHAT_MEMORY_LIMIT", "8"))
# 對話後面那輪「記憶萃取」的獨立逾時。萃取只要產出一小段 JSON，不需要等
# 跟主對話一樣久；給太長會讓串流在回完覆之後長時間靜默，看起來像卡死。
EXTRACT_TIMEOUT_S = float(os.environ.get("EXTRACT_TIMEOUT", "180"))
# 萃取只要產出一小段 JSON，不該讓模型自由發揮。限制輸出長度可以大幅縮短這輪
# 的等待時間（本機 CPU 上 8B 模型每個 token 都不便宜）。
EXTRACT_MAX_TOKENS = int(os.environ.get("EXTRACT_MAX_TOKENS", "400"))
# 萃取期間多久送一次 SSE 註解心跳。串流回完 token 到送 done 之間本來會完全
# 沒有資料，這段靜默容易被中間設備／代理當成閒置連線切斷。
EXTRACT_KEEPALIVE_S = float(os.environ.get("EXTRACT_KEEPALIVE", "10"))


def _build_memory_context(limit: int = 0) -> str:
    """把權重最高的記憶節點壓成每次對話的系統提示（讓本機模型記得你是誰）。"""
    n = limit or CHAT_MEMORY_LIMIT
    nodes = db.get_nodes()
    if not nodes:
        return ""
    top = sorted(nodes, key=lambda x: float(x.get("weight") or 0), reverse=True)[
        : max(1, min(n, 20))
    ]
    rules = [x for x in top if x.get("category") == "rule"]
    others = [x for x in top if x.get("category") != "rule"]

    def fmt(x: dict[str, Any]) -> str:
        s = (x.get("summary") or "").strip()
        head = f"{x.get('label') or x['id']}（{x.get('category', 'topic')}，權重 {float(x.get('weight') or 0):.1f}）"
        return head + (f"：{s}" if s else "")

    lines = ["## 使用者長期記憶（你是 SynapseBrain，每次回答都要參考）"]
    lines += ["- " + fmt(x) for x in others]
    if rules:
        lines.append("### 必須遵守的規則")
        lines += ["- " + fmt(r) for r in rules]
    return "\n".join(lines)


def _build_chat_system() -> str:
    """每次對話的完整系統提示：人設＋語言＋長期記憶。串流/非串流共用。"""
    mem_ctx = _build_memory_context()
    return CHAT_SYSTEM + ("\n\n" + mem_ctx if mem_ctx else "")

_ollama_proc: Optional[subprocess.Popen] = None
_ollama_state: dict[str, Any] = {"managed": False, "pulling": False, "pull_error": None}


def probe_ollama(timeout: float = 2.0) -> dict[str, Any]:
    """偵測 Ollama 是否活著。保證不拋錯，供 health/自啟/前端狀態用。"""
    info: dict[str, Any] = {"reachable": False, "version": None, "models": []}
    try:
        with httpx.Client(timeout=timeout) as client:
            v = client.get(f"{OLLAMA_URL}/api/version")
            if v.is_success:
                info["version"] = v.json().get("version")
                info["reachable"] = True
            t = client.get(f"{OLLAMA_URL}/api/tags")
            if t.is_success:
                info["models"] = [m.get("name") for m in t.json().get("models", [])]
    except Exception:
        pass
    return info


def _model_present(models: list[str]) -> bool:
    base = OLLAMA_MODEL.split(":")[0]
    return any((m or "") == OLLAMA_MODEL or (m or "").startswith(base + ":") for m in models)


def _wait_reachable(deadline_s: float = 15.0) -> bool:
    end = time.time() + deadline_s
    while time.time() < end:
        if probe_ollama()["reachable"]:
            return True
        time.sleep(0.5)
    return False


def _pull_model_background() -> None:
    def _run() -> None:
        _ollama_state["pulling"] = True
        try:
            r = subprocess.run(
                ["ollama", "pull", OLLAMA_MODEL],
                capture_output=True, text=True, timeout=1800,
            )
            if r.returncode != 0:
                _ollama_state["pull_error"] = (r.stderr or r.stdout or "pull failed")[-500:]
            else:
                print(f"[synapse] 模型 {OLLAMA_MODEL} 下載完成。")
        except Exception as exc:
            _ollama_state["pull_error"] = str(exc)[-500:]
        finally:
            _ollama_state["pulling"] = False

    threading.Thread(target=_run, daemon=True).start()


def ensure_ollama() -> dict[str, Any]:
    """server 啟動時呼叫：Ollama 沒跑就試著幫你開。保證不拋錯、不卡死啟動。"""
    global _ollama_proc
    status = probe_ollama()
    if status["reachable"]:
        return {"started": False, **status}
    if not OLLAMA_AUTOSTART:
        return {"started": False, "skipped": "已停用（OLLAMA_AUTOSTART=0）", **status}
    if shutil.which("ollama") is None:
        print("[synapse] 找不到 ollama 指令，跳過自動啟動（先照官網安裝 Ollama，聊天會用示範回覆）。")
        return {"started": False, "skipped": "ollama binary not found", **status}
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _ollama_proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        _ollama_state["managed"] = True
        print("[synapse] 已自動啟動 ollama serve（關掉本程式時會一併關掉；本來就有跑的話不會動它）。")
    except Exception as exc:
        print(f"[synapse] 自動啟動 ollama 失敗：{exc}")
        return {"started": False, "skipped": str(exc), **status}
    if _wait_reachable():
        status = probe_ollama()
        status["started"] = True
    else:
        status["started"] = False
        status["skipped"] = "ollama serve 啟動逾時（15 秒連不上）"
        return status
    if not _model_present(status.get("models", [])):
        if OLLAMA_AUTOPULL and not _ollama_state["pulling"]:
            print(f"[synapse] 模型 {OLLAMA_MODEL} 尚未下載，背景下載中…")
            _pull_model_background()
        else:
            print(f"[synapse] 模型 {OLLAMA_MODEL} 尚未下載，請執行：ollama pull {OLLAMA_MODEL}")
    return status


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_ollama()
    try:
        yield
    finally:
        global _ollama_proc
        proc, _ollama_proc = _ollama_proc, None
        # 只關「我們自己啟動的」；使用者本來就開著的不碰
        if proc is not None and _ollama_state.get("managed"):
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            print("[synapse] 已關閉自動啟動的 ollama serve。")


app = FastAPI(title="SynapseBrain", version="1.1.0", lifespan=lifespan)

db.init_db()
try:
    db.seed_if_empty()
except Exception:
    pass


# ---------- Schemas ----------
class NodeIn(BaseModel):
    id: str
    label: Optional[str] = None
    category: str = "topic"
    weight: float = 1.0
    summary: str = ""


class EdgeIn(BaseModel):
    source: str
    target: str
    relation: str = "related_to"
    strength: float = 1.0


class ChatIn(BaseModel):
    message: str
    remember: bool = True  # 聊完是否自動萃取重點寫回圖譜


class CompileIn(BaseModel):
    focus_topic: Optional[str] = None
    limit: int = 8


class IngestIn(BaseModel):
    text: str = Field(default="")


# ---------- Graph Management ----------
def _decay_excluding(touched_ids: list[str]) -> int:
    """衰減「本次沒被碰到」的節點（topic/skill 微幅淡出，persona/rule 不動）。

    傳給 compiler.apply_ingest 的 decay_fn，讓「一輪對話 = 一次衰減」。
    """
    return db.decay_others(exclude_ids=touched_ids)


@app.get("/api/graph")
def api_graph():
    return db.get_graph()


@app.post("/api/nodes", status_code=201)
def api_upsert_node(node: NodeIn):
    try:
        return db.upsert_node(node.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/nodes/{node_id}/boost")
def api_boost_node(node_id: str, amount: float = 0.5):
    updated = db.boost_node(node_id, amount)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"node {node_id!r} not found")
    # 手動 boost 也是一個事件：讓其他 topic/skill 淡出，避免舊記憶一直佔著前面
    _decay_excluding([node_id])
    return updated


@app.delete("/api/nodes/{node_id}")
def api_delete_node(node_id: str):
    if not db.delete_node(node_id):
        raise HTTPException(status_code=404, detail=f"node {node_id!r} not found")
    return {"deleted": node_id}


@app.post("/api/edges", status_code=201)
def api_add_edge(edge: EdgeIn):
    try:
        return db.add_edge(
            edge.source, edge.target, edge.relation, edge.strength
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/seed-demo")
def api_seed_demo():
    """寫入範例圖譜（冪等合併），方便第一次體驗。"""
    counts = db.seed_demo()
    return {"seeded": True, "counts": counts, "graph": db.get_graph()}


# ---------- Local LLM ----------
async def _ollama_generate(
    prompt: str,
    timeout: float = 180.0,
    system: Optional[str] = None,
    options_override: Optional[dict[str, Any]] = None,
    json_mode: bool = False,
) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    """Call Ollama /api/generate (non-streaming).

    Returns (data, error). HTTP 2xx -> (parsed JSON, None).
    error is one of:
      - {"kind": "unreachable", ...}    Ollama 根本沒開 / 連不上
      - {"kind": "timeout", ...}       連得上，但沒在期限內回應（模型太慢／卡住）
      - {"kind": "model_missing", ...}  Ollama 活著，但指定的模型還沒下載（Ollama 回 404）
      - {"kind": "http_error", ...}     其他 HTTP 錯誤

    json_mode=True 會送出 format="json"，強迫模型只吐合法 JSON、不夾帶
    Markdown 或前言——對記憶萃取這種「要結構化輸出」的呼叫特別有用。
    """
    url = f"{OLLAMA_URL}/api/generate"
    try:
        payload: dict[str, Any] = {
            "model": OLLAMA_MODEL, "prompt": prompt, "stream": False,
            # 低溫＝穩定聽話，萃取 JSON 更可靠
            "options": options_override if options_override is not None
            else _ollama_options(),
        }
        if json_mode:
            payload["format"] = "json"
        if system:
            payload["system"] = system  # Ollama 原生系統指令，不污染使用者對話
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json(), None
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else None
        detail = ""
        if exc.response is not None:
            try:
                body = exc.response.json()
                detail = str(body.get("error", body))
            except Exception:
                detail = (exc.response.text or "")[:300]
        # Ollama 對「模型不存在」回 404，例如：
        # model 'llama3:8b' not found, try pulling it first
        if status == 404 and "model" in detail.lower():
            return None, {"kind": "model_missing", "detail": detail}
        return None, {"kind": "http_error", "status": status, "detail": detail[:300]}
    except httpx.TimeoutException as exc:
        # 必須在下面那個 except Exception 之前抓：逾時的 str() 通常是空字串，
        # 混到「unreachable」裡會讓人誤以為 Ollama 沒開，拿到完全錯的建議。
        return None, {
            "kind": "timeout",
            "detail": f"{type(exc).__name__}：等待 Ollama 回應超過 {timeout:g} 秒"
                      f"（模型 {OLLAMA_MODEL} 可能太慢或卡住）",
        }
    except Exception as exc:
        return None, {
            "kind": "unreachable",
            "detail": f"{type(exc).__name__}: {exc}"[:300],
        }


def _mock_text(err: dict[str, Any], message: str) -> str:
    """把 Ollama 錯誤分類轉成給使用者看的中文訊息（串流/非串流共用）。"""
    if err["kind"] == "model_missing":
        return (
            "【Ollama 有開，但模型還沒準備好】\n"
            f"{err.get('detail')}\n"
            f"請等 `ollama pull {OLLAMA_MODEL}` 跑完再試一次。"
        )
    if err["kind"] == "timeout":
        return (
            "【Ollama 回應逾時】\n"
            f"{err.get('detail')}\n"
            f"Ollama 有在跑，只是本機模型太慢。可以換小一點的模型"
            f"（$env:OLLAMA_MODEL=\"qwen2.5:1.5b\"），或稍後再試一次。\n"
            f"（若 Ollama 剛重啟、模型還沒載入，第一次也會比較久。）"
        )
    if err["kind"] == "http_error":
        return (
            f"【Ollama 回傳錯誤（HTTP {err.get('status')}）】\n"
            f"{err.get('detail') or '（無訊息）'}"
        )
    return (
        "【示範回覆 — 連不上 Ollama】\n"
        f"你說：{message}\n"
        f"想啟用真正對話請執行 `ollama serve` 並 `ollama pull {OLLAMA_MODEL}`。"
    )


def _sse(obj: dict[str, Any]) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


async def _extract_memory(user_msg: str, assistant_msg: str) -> dict[str, Any]:
    """把一輪對話萃取成圖譜更新。

    保證不拋錯：任何失敗都會變成帶 `error` 的回傳值。這是刻意的——記憶寫回
    是附加價值，不該讓它把已經成功產生的對話回覆一起拖垮。

    可觀測性：失敗時一定會把「模型吐的原文」印到 terminal。最難查的就是
    「HTTP 200、沒有錯誤訊息、但圖譜沒長東西」這種情況，光看前端永遠查不出來。
    """
    try:
        existing_ids = [n["id"] for n in db.get_nodes()]
        extraction, err = await _ollama_generate(
            _build_extraction_prompt(user_msg, assistant_msg, existing_ids),
            timeout=EXTRACT_TIMEOUT_S,
            # format="json" 讓 Ollama 保證回傳合法 JSON，模型再怎麼亂加
            # ``` 標記或英文前言也不會破壞解析（compiler 兩種都吃）。
            json_mode=True,
            options_override={
                "temperature": 0.1,          # 萃取要穩定，不要創意
                "num_predict": EXTRACT_MAX_TOKENS,
            },
        )
        if not extraction:
            kind = (err or {}).get("kind", "unknown")
            detail = (err or {}).get("detail", "")
            msg = f"記憶寫回略過（{kind}）：{detail}"
            print(f"[synapse] {msg}")
            return {"error": msg}
        raw = extraction.get("response", "") or ""
        summary = compiler_mod.apply_ingest(
            raw,
            upsert_node_fn=db.upsert_node,
            boost_node_fn=db.boost_node,
            add_edge_fn=lambda s, t, r="related_to": db.add_edge(s, t, r),
            decay_fn=_decay_excluding,
        )
        summary["graph"] = db.get_graph()
        if summary.get("errors"):
            print(f"[synapse] 記憶寫回部分失敗：{summary['errors']}")
        if not summary["blocks_found"]:
            # 沒有認出任何 payload：把模型吐的原文印出來，否則只能靠猜。
            # 「沒報錯但節點沒增加」正是最難查的那種故障。
            print(
                "[synapse] 萃取結果解析不到 brain-update，"
                f"原始輸出（{len(raw)} 字元）：\n{_dump_raw(raw)}"
            )
        return summary
    except Exception as exc:
        print(f"[synapse] 記憶寫回失敗：{exc}")
        return {"error": f"記憶寫回失敗：{exc}"}


def _dump_raw(raw: str, limit: int = 1200) -> str:
    """可觀測性用：把模型原始輸出截斷印出來，空白與換行保留原樣。

    不 strip 是故意的——8B 模型常在 JSON 前後加廢話或 ``` 標記，原樣印出來
    才看得到它到底幹了什麼。
    """
    text = (raw or "").replace("\r", "")
    if len(text) <= limit:
        return text or "（空字串）"
    return f"{text[:limit]}\n...（已截斷，原始長度 {len(text)} 字元）"


def _build_extraction_prompt(
    user_msg: str, assistant_msg: str, existing_ids: list[str]
) -> str:
    id_list = "、".join(existing_ids[:30]) if existing_ids else "（目前無節點）"
    return f"""你是記憶萃取器。以下是使用者與 AI 助理的一段對話，以及使用者記憶圖譜中現有的節點 id。

現有節點 id：{id_list}

對話：
使用者：{user_msg}
助理：{assistant_msg}

任務：判斷對話中是否有值得長期記住的新知識、技能、偏好或規則。
- 所有 label 與 summary 一律使用繁體中文（台灣用語），絕對不要用英文；專有名詞可保留原文。
- 只輸出一個 JSON 物件，不要加任何說明文字，也不要加 Markdown 標記。schema：
  {{"new_nodes": [{{"id": "小寫連字號", "label": "名稱", "summary": "一句話說明", "weight": 1.0}}],
   "boost_nodes": ["已存在的id"],
   "new_edges": [{{"source": "id", "target": "id", "relation": "relates_to"}}]}}
- 沒有值得記的就回傳空的陣列，不要捏造。
- edge 的端點必須是現有 id 或本次 new_nodes 引入的 id；relation 只能是 depends_on、part_of、relates_to 三選一，不要自創（如 provides）。"""


@app.post("/api/local-chat")
async def api_local_chat(payload: ChatIn):
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="message must be non-empty")
    data, err = await _ollama_generate(
        _with_lang_suffix(message), timeout=180.0, system=_build_chat_system()
    )
    if err is not None:
        # 連不上/模型缺失都走中文示範訊息，且不做記憶寫回
        return {
            "response": _mock_text(err, message),
            "model": f"{OLLAMA_MODEL}（示範）",
            "mock": True,
            "memory": None,
        }
    reply = data.get("response", "")
    result: dict[str, Any] = {
        "response": reply,
        "model": data.get("model", OLLAMA_MODEL),
        "mock": False,
        "memory": None,
    }
    if payload.remember and reply.strip():
        # 第二輪：請 LLM 萃取值得記的重點，轉成 brain-update 寫回圖譜。
        # 萃取保證不拋錯，失敗只會在 memory.error 裡回報，不影響上面的回覆。
        result["memory"] = await _extract_memory(message, reply)
    if _unload_after_chat():
        await _ollama_unload()  # 用完即走：模型卸載，server 照跑
    return result


@app.post("/api/local-chat-stream")
async def api_local_chat_stream(payload: ChatIn):
    """串流版對話：Ollama token 以 SSE 逐塊送出，最後一包夾帶記憶寫回結果。"""
    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="message must be non-empty")

    async def gen():
        full: list[str] = []
        try:
            req: dict[str, Any] = {
                "model": OLLAMA_MODEL, "prompt": _with_lang_suffix(message),
                "stream": True,
                "options": _ollama_options(),
                "system": _build_chat_system(),  # 人設＋記憶：跟非串流同一份
            }
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream(
                    "POST", f"{OLLAMA_URL}/api/generate", json=req
                ) as resp:
                    if resp.status_code != 200:
                        raw = await resp.aread()
                        try:
                            parsed = json.loads(raw.decode(errors="replace") or "{}")
                            detail = str(
                                parsed.get("error", parsed)
                                if isinstance(parsed, dict) else parsed
                            )
                        except Exception:
                            detail = raw.decode(errors="replace")[:300]
                        if resp.status_code == 404 and "model" in detail.lower():
                            err: dict[str, Any] = {"kind": "model_missing", "detail": detail}
                        else:
                            err = {"kind": "http_error", "status": resp.status_code,
                                   "detail": detail[:300]}
                        yield _sse({"token": _mock_text(err, message)})
                        yield _sse({"done": True, "mock": True, "memory": None,
                                    "model": f"{OLLAMA_MODEL}（示範）"})
                        return
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except Exception:
                            continue
                        token = chunk.get("response", "")
                        if token:
                            full.append(token)
                            yield _sse({"token": token})
                        if chunk.get("done"):
                            break
        except Exception as exc:
            detail = str(exc)[:300]
            print(f"[synapse] 串流對話中斷：{detail}")
            if full:
                # 已經送出部分 token 了：不要丟掉使用者拿到的回覆，也不要用
                # 示範訊息去混淆它，直接如實回報中斷並正常收尾。
                yield _sse({"token": f"\n\n【串流中斷：{detail}】"})
                yield _sse({"done": True, "mock": False, "memory": None,
                            "model": OLLAMA_MODEL})
            else:
                yield _sse({"token": _mock_text(
                    {"kind": "unreachable", "detail": detail}, message)})
                yield _sse({"done": True, "mock": True, "memory": None,
                            "model": f"{OLLAMA_MODEL}（示範）"})
            return
        reply = "".join(full)
        mem: Optional[dict[str, Any]] = None
        if payload.remember and reply.strip():
            # 萃取跑在獨立 task：等待期間定期送 SSE 註解心跳，讓連線維持活動。
            # 沒有這段的話，「回完 token → 送出 done」之間會有幾十秒完全靜默，
            # 中間設備很容易把它當閒置連線切掉，前端就只會看到「串流中斷」。
            task = asyncio.create_task(_extract_memory(message, reply))
            try:
                while True:
                    finished, _ = await asyncio.wait(
                        {task}, timeout=EXTRACT_KEEPALIVE_S
                    )
                    if finished:
                        break
                    # 用 data: 事件而不是 ": 註解"：註解雖然也算流量，但部分
                    # 中間設備會吞掉；data 事件保證送達，而且前端可以拿它來
                    # 顯示「正在整理記憶」，避免使用者看到一片空白以為當掉。
                    yield _sse({"busy": "正在整理記憶…"})
                mem = task.result()  # _extract_memory 保證不拋錯
            except asyncio.CancelledError:
                task.cancel()
                raise
            except Exception as exc:  # 保險：連這裡壞掉都還是要送 done
                print(f"[synapse] 記憶萃取階段例外：{exc}")
                mem = {"error": f"記憶寫回失敗：{exc}"}
        yield _sse({"done": True, "mock": False, "memory": mem, "model": OLLAMA_MODEL})
        if _unload_after_chat():
            await _ollama_unload()  # 用完即走：模型卸載，server 照跑

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- Compiler & Ingestion ----------
@app.post("/api/compile-prompt")
def api_compile(payload: CompileIn):
    nodes = db.get_nodes()
    edges = db.get_edges()
    return compiler_mod.compile_prompt(
        nodes, edges, focus_topic=payload.focus_topic, limit=payload.limit
    )


@app.post("/api/ingest")
def api_ingest(payload: IngestIn):
    summary = compiler_mod.apply_ingest(
        payload.text,
        upsert_node_fn=db.upsert_node,
        boost_node_fn=db.boost_node,
        add_edge_fn=lambda s, t, r="related_to": db.add_edge(s, t, r),
        decay_fn=_decay_excluding,
    )
    summary["graph"] = db.get_graph()
    return summary


# ---------- Frontend ----------
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "SynapseBrain API — static/index.html not found"}


@app.get("/api/health")
def health() -> dict[str, Any]:
    probe = probe_ollama()
    return {
        "status": "ok",
        "ollama": {
            "reachable": probe["reachable"],
            "version": probe["version"],
            "model": OLLAMA_MODEL,
            "model_present": _model_present(probe["models"]),
            "managed": _ollama_state["managed"],
            "pulling": _ollama_state["pulling"],
            "pull_error": _ollama_state["pull_error"],
        },
    }


if __name__ == "__main__":
    import uvicorn

    port = resolve_port(HOST)
    write_port_file(port)
    print(f"[synapse] SynapseBrain 啟動於 http://{HOST}:{port}  (port 記錄於 {PORT_FILE.name})")
    try:
        uvicorn.run(app, host=HOST, port=port)
    finally:
        clear_port_file()  # 正常結束或例外都不留殘留的 .port
