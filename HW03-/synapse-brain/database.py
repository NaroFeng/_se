"""SQLite helper for SynapseBrain."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Optional

# Default DB lives next to this file so `python main.py` works out of the box.
DEFAULT_DB_PATH = str(Path(__file__).resolve().parent / "synapse.db")


def resolve_db_path(explicit: Optional[str] = None) -> str:
    return explicit or os.environ.get("SYNAPSE_DB") or DEFAULT_DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    category TEXT DEFAULT 'topic',
    weight REAL DEFAULT 1.0,
    summary TEXT DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    relation TEXT DEFAULT 'related_to',
    strength REAL DEFAULT 1.0,
    FOREIGN KEY(source) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(target) REFERENCES nodes(id) ON DELETE CASCADE,
    UNIQUE(source, target, relation)
);
"""

VALID_CATEGORIES = {"topic", "skill", "persona", "rule"}

# Event-driven decay: 只有 topic/skill 會被慢慢淡出；persona/rule 是核心人設與
# 硬性規則，必須穩定，所以不參與衰減。
DECAYABLE_CATEGORIES = ("topic", "skill")
DECAY_FACTOR = 0.98
DECAY_FLOOR = 0.1


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = resolve_db_path(db_path)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")  # 讀寫撞車時等 5 秒，別直接報錯
    # 自我修復：每次連線都確保資料表存在。否則只要 synapse.db 在
    # server 執行中被刪除/換掉，之後每個請求都會 500（no such table）。
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def init_db(db_path: Optional[str] = None) -> str:
    path = resolve_db_path(db_path)
    conn = get_connection(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return path


def _clamp_weight(w: float) -> float:
    try:
        w = float(w)
    except (TypeError, ValueError):
        w = 1.0
    return max(0.1, min(10.0, w))


def _touch(conn: sqlite3.Connection, node_id: str) -> None:
    conn.execute(
        "UPDATE nodes SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (node_id,),
    )


def upsert_node(
    node: dict[str, Any], db_path: Optional[str] = None
) -> dict[str, Any]:
    """Create or update a node. Returns the stored row as dict."""
    if not node.get("id"):
        raise ValueError("node 'id' is required")
    node_id = str(node["id"]).strip()
    if not node_id:
        raise ValueError("node 'id' must be non-empty")
    label = str(node.get("label") or node_id)
    category = str(node.get("category") or "topic")
    if category not in VALID_CATEGORIES:
        category = "topic"
    weight = _clamp_weight(node.get("weight", 1.0))
    summary = str(node.get("summary") or "")

    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO nodes (id, label, category, weight, summary)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                label = excluded.label,
                category = excluded.category,
                weight = excluded.weight,
                summary = excluded.summary,
                updated_at = CURRENT_TIMESTAMP
            """,
            (node_id, label, category, weight, summary),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_node(node_id: str, db_path: Optional[str] = None) -> Optional[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_nodes(
    order_by_weight: bool = True,
    limit: Optional[int] = None,
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM nodes"
    if order_by_weight:
        sql += " ORDER BY weight DESC, updated_at DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    conn = get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def delete_node(node_id: str, db_path: Optional[str] = None) -> bool:
    conn = get_connection(db_path)
    try:
        # Remove adjacent edges explicitly (FK cascade is also on).
        conn.execute(
            "DELETE FROM edges WHERE source = ? OR target = ?", (node_id, node_id)
        )
        cur = conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def boost_node(
    node_id: str, amount: float = 0.5, db_path: Optional[str] = None
) -> Optional[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if not row:
            return None
        new_weight = _clamp_weight(float(row["weight"]) + float(amount))
        conn.execute(
            "UPDATE nodes SET weight = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_weight, node_id),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return dict(updated)
    finally:
        conn.close()


def decay_others(
    exclude_ids: Optional[list[str]] = None,
    factor: float = DECAY_FACTOR,
    floor: float = DECAY_FLOOR,
    db_path: Optional[str] = None,
) -> int:
    """Event-driven decay：一行 SQL 讓「本次沒被碰到」的節點權重微幅下降。

    只作用在 topic / skill（見 DECAYABLE_CATEGORIES），persona 與 rule 不動，
    這樣核心人設和硬性規則不會被時間稀釋掉。權重不會低於 `floor`。

    Returns the number of rows touched.
    """
    try:
        factor = float(factor)
    except (TypeError, ValueError):
        factor = DECAY_FACTOR
    if not 0.0 <= factor <= 1.0:  # factor > 1 等於偷偷加權，不符合衰減語意
        factor = DECAY_FACTOR
    ids = [str(i) for i in (exclude_ids or []) if str(i).strip()]

    sql = (
        "UPDATE nodes SET weight = MAX(?, ROUND(weight * ?, 3)) "
        f"WHERE category IN ({','.join('?' * len(DECAYABLE_CATEGORIES))})"
    )
    params: list[Any] = [float(floor), factor, *DECAYABLE_CATEGORIES]
    if ids:  # 本次被更新過的節點不衰減，否則剛 boost 完立刻被扣回去
        sql += f" AND id NOT IN ({','.join('?' * len(ids))})"
        params += ids

    conn = get_connection(db_path)
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    finally:
        conn.close()


def add_edge(
    source: str, target: str, relation: str = "related_to",
    strength: float = 1.0, db_path: Optional[str] = None,
) -> dict[str, Any]:
    if not source or not target:
        raise ValueError("edge 'source' and 'target' are required")
    relation = str(relation or "related_to")
    try:
        strength = float(strength)
    except (TypeError, ValueError):
        strength = 1.0
    conn = get_connection(db_path)
    try:
        src = conn.execute("SELECT id FROM nodes WHERE id = ?", (source,)).fetchone()
        dst = conn.execute("SELECT id FROM nodes WHERE id = ?", (target,)).fetchone()
        if not src or not dst:
            raise ValueError(
                f"both endpoints must exist (missing: "
                f"{'' if src else source} {'' if dst else target}".strip() + ")"
            )
        conn.execute(
            """
            INSERT INTO edges (source, target, relation, strength)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(source, target, relation) DO UPDATE SET strength = excluded.strength
            """,
            (source, target, relation, strength),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM edges WHERE source = ? AND target = ? AND relation = ?",
            (source, target, relation),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_edges(db_path: Optional[str] = None) -> list[dict[str, Any]]:
    conn = get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM edges").fetchall()]
    finally:
        conn.close()


def get_graph(db_path: Optional[str] = None) -> dict[str, list[dict[str, Any]]]:
    return {"nodes": get_nodes(db_path=db_path), "edges": get_edges(db_path=db_path)}


def get_neighbors(
    node_id: str, db_path: Optional[str] = None
) -> list[dict[str, Any]]:
    """Nodes directly connected to node_id (either direction)."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT n.* FROM nodes n
            JOIN edges e ON (e.source = ? AND e.target = n.id)
                          OR (e.target = ? AND e.source = n.id)
            WHERE n.id != ?
            """,
            (node_id, node_id, node_id),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


DEMO_NODES = [
    {"id": "ai-assistant", "label": "AI 助手", "category": "persona", "weight": 3.0,
     "summary": "本地 AI 助手人設：親切、簡潔，一律用繁體中文回答。"},
    {"id": "python", "label": "Python", "category": "skill", "weight": 2.5,
     "summary": "核心語言：腳本、API 與資料處理。"},
    {"id": "llm-apps", "label": "LLM 應用", "category": "topic", "weight": 2.2,
     "summary": "聊天機器人、摘要、萃取等大型語言模型應用。"},
    {"id": "zh-reply", "label": "繁中回覆", "category": "rule", "weight": 2.4,
     "summary": "規則：回答一律使用繁體中文（台灣用語）。"},
    {"id": "fastapi", "label": "FastAPI", "category": "skill", "weight": 2.0,
     "summary": "非同步 Python Web 框架，本專案後端用它。"},
    {"id": "rag", "label": "RAG 檢索增強", "category": "topic", "weight": 2.0,
     "summary": "先檢索相關文件再生成，降低幻覺。"},
    {"id": "docker", "label": "Docker", "category": "skill", "weight": 1.8,
     "summary": "容器化部署，把服務包成映像檔到處跑。"},
    {"id": "ollama", "label": "Ollama", "category": "skill", "weight": 1.6,
     "summary": "本機 LLM 執行環境，提供 API 給 App 呼叫。"},
    {"id": "system-design", "label": "系統設計", "category": "topic", "weight": 1.5,
     "summary": "API、快取、佇列與擴展性取捨。"},
    {"id": "prompt-engineering", "label": "提示工程", "category": "topic", "weight": 1.4,
     "summary": "system prompt、few-shot、結構化輸出等技巧。"},
    {"id": "streaming", "label": "串流輸出", "category": "topic", "weight": 1.2,
     "summary": "SSE 逐字輸出，降低等待感。"},
]

DEMO_EDGES = [
    ("fastapi", "python", "depends_on"),
    ("llm-apps", "python", "depends_on"),
    ("rag", "llm-apps", "part_of"),
    ("rag", "ollama", "depends_on"),
    ("prompt-engineering", "llm-apps", "relates_to"),
    ("ollama", "llm-apps", "relates_to"),
    ("docker", "fastapi", "relates_to"),
    ("ai-assistant", "llm-apps", "part_of"),
    ("zh-reply", "ai-assistant", "relates_to"),
    ("streaming", "fastapi", "relates_to"),
    ("streaming", "llm-apps", "relates_to"),
    ("system-design", "fastapi", "relates_to"),
]


def seed_demo(db_path: Optional[str] = None) -> dict[str, int]:
    """寫入（或合併）範例圖譜，冪等：重跑不會產生重複。"""
    counts = {"nodes": 0, "edges": 0}
    for n in DEMO_NODES:
        upsert_node(n, db_path=db_path)
        counts["nodes"] += 1
    for s, t, r in DEMO_EDGES:
        try:
            add_edge(s, t, r, 1.0, db_path=db_path)
            counts["edges"] += 1
        except ValueError:
            pass
    return counts


def seed_if_empty(db_path: Optional[str] = None) -> None:
    if get_nodes(db_path=db_path):
        return
    seed_demo(db_path=db_path)
