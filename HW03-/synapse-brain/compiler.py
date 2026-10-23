"""Prompt compilation + brain-update ingestion engine."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

# Strict form, kept for counting/malformed reporting.
BRAIN_UPDATE_RE = re.compile(
    r"```brain-update([^\n]*)\n(.*?)```", re.IGNORECASE | re.DOTALL
)

# 小模型常常不照格式：把 ```brain-update 標成 ``` 或 ```json，前面還加一句
# "Here is the brain update code block:"。只認標籤的話，記憶寫回會安靜地
# 什麼都沒寫進去而不報錯。所以改成先抓「所有」fenced block，再用內容能不能
# 解析成 brain-update payload 來判斷，不去相信模型有聽話。
FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)
BRAIN_UPDATE_KEYS = ("new_nodes", "boost_nodes", "new_edges")
# 這些值都必須是陣列。少了型別檢查，程式碼裡剛好出現 {"new_nodes": "..."}
# 就會被當成 payload 吞進圖譜。
BRAIN_UPDATE_SHAPE = {"new_nodes": list, "boost_nodes": list, "new_edges": list}
ALLOWED_FENCE_TAGS = {"", "json", "brain-update", "brainupdate", "brain_update"}


def _node_sort_key(n: dict[str, Any]) -> float:
    try:
        return float(n.get("weight", 0.0))
    except (TypeError, ValueError):
        return 0.0


def compile_prompt(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    focus_topic: Optional[str] = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Build an external system prompt from the highest-weight nodes.

    If focus_topic matches a node id, that node plus its 1-hop neighbours
    are pinned to the top of the selection.
    """
    limit = max(1, min(int(limit or 8), 50))
    ranked = sorted(nodes, key=_node_sort_key, reverse=True)

    pinned: list[dict[str, Any]] = []
    if focus_topic:
        focus = next((n for n in nodes if n["id"] == focus_topic), None)
        if focus:
            pinned.append(focus)
            neighbour_ids: set[str] = set()
            for e in edges:
                if e.get("source") == focus_topic and e.get("target"):
                    neighbour_ids.add(e["target"])
                elif e.get("target") == focus_topic and e.get("source"):
                    neighbour_ids.add(e["source"])
            by_id = {n["id"]: n for n in nodes}
            neighbours = [
                by_id[i] for i in neighbour_ids if i in by_id and i != focus_topic
            ]
            neighbours.sort(key=_node_sort_key, reverse=True)
            pinned.extend(neighbours)

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n in pinned + ranked:
        if n["id"] not in seen:
            seen.add(n["id"])
            selected.append(n)
        if len(selected) >= limit:
            break
    selected = selected[:limit]

    sel_ids = {n["id"] for n in selected}
    relevant_edges = [
        e for e in edges if e.get("source") in sel_ids and e.get("target") in sel_ids
    ]

    lines: list[str] = []
    lines.append("# SynapseBrain — Compiled Context Prompt")
    lines.append("")
    lines.append("You are assisting a user whose long-term memory is summarized below.")
    lines.append("Use this context to personalize answers and respect constraints.")
    lines.append("")
    lines.append("## Active Memory Nodes (sorted by weight)")
    if selected:
        for n in selected:
            lines.append(
                f"- **{n.get('label', n['id'])}** "
                f"(id: `{n['id']}` | category: {n.get('category', 'topic')} "
                f"| weight: {float(n.get('weight', 1.0)):.1f})"
            )
            if n.get("summary"):
                lines.append(f"  - Context: {n['summary']}")
    else:
        lines.append("- (no memory nodes yet — treat the user as new)")
    lines.append("")
    lines.append("## Known Relations")
    if relevant_edges:
        for e in relevant_edges:
            lines.append(
                f"- `{e.get('source')}` --[{e.get('relation', 'related_to')}]--> "
                f"`{e.get('target')}`"
            )
    else:
        lines.append("- (no recorded relations)")
    lines.append("")
    lines.append("## Constraint Instructions")
    lines.append("- Prefer the user's strongest skills/topics unless told otherwise.")
    lines.append("- Persona and rule nodes override generic behaviour.")
    lines.append("- Do not invent node IDs; reuse the exact `id` values above.")
    lines.append("")
    lines.append("## Ingestion Protocol (IMPORTANT)")
    lines.append(
        "At the very end of your reply, append ONE fenced code block tagged "
        "`brain-update` containing a single JSON object with this exact schema:"
    )
    lines.append("")
    lines.append("```brain-update")
    lines.append("{")
    lines.append('  "new_nodes": [{"id": "...", "label": "...", "summary": "...", "weight": 1.0}],')
    lines.append('  "boost_nodes": ["existing_id_1"],')
    lines.append('  "new_edges": [{"source": "...", "target": "...", "relation": "..."}]')
    lines.append("}")
    lines.append("```")
    lines.append("")
    lines.append(
        "Rules: keep ids lowercase-hyphenated; only list `boost_nodes` for nodes "
        "that already exist; every edge endpoint must be an existing node id or "
        "an id introduced in the same `new_nodes` array."
    )

    return {
        "prompt": "\n".join(lines),
        "focus_topic": focus_topic,
        "node_ids": [n["id"] for n in selected],
        "count": len(selected),
    }


def _parse_json_body(body: str) -> Any:
    """Parse a fenced block body as JSON, tolerating leading chatter."""
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(body[start : end + 1])
    except json.JSONDecodeError:
        return None


def _looks_like_brain_update(data: Any) -> bool:
    """True only for an object that carries brain-update keys with sane types."""
    if not isinstance(data, dict):
        return False
    present = [k for k in BRAIN_UPDATE_KEYS if k in data]
    if not present:
        return False
    return all(isinstance(data[k], BRAIN_UPDATE_SHAPE[k]) for k in present)


def extract_brain_updates(raw_text: str) -> list[dict[str, Any]]:
    """Extract and JSON-parse every brain-update payload found in raw_text.

    A block only counts when it is not labelled as some other language *and*
    its body parses into a payload object carrying the expected keys with list
    values, so unrelated code blocks are ignored.

    Handles every shape models actually produce: a ```brain-update /
    ```json / bare ``` fence, bare JSON with no fence at all (Ollama
    `format: "json"` mode), and either of those preceded by chatter such as
    "Here is the brain update code block:".
    """
    text = raw_text or ""
    payloads: list[dict[str, Any]] = []
    seen: set[str] = set()

    def take(candidate: str) -> None:
        data = _parse_json_body(candidate)
        if _looks_like_brain_update(data):
            key = json.dumps(data, sort_keys=True, ensure_ascii=False)
            if key not in seen:  # 同一份 payload 可能被 fenced 與整段各抓到一次
                seen.add(key)
                payloads.append(data)

    for m in FENCE_RE.finditer(text):
        tag = (m.group(1) or "").strip().lower()
        if tag in ALLOWED_FENCE_TAGS:
            take(m.group(2))
    take(text)  # 裸 JSON（format="json" 模式）沒有 fence，只能掃整段
    return payloads


def _norm_id(v: Any) -> str:
    return str(v or "").strip()


def apply_ingest(
    raw_text: str,
    *,
    upsert_node_fn,
    boost_node_fn,
    add_edge_fn,
    decay_fn=None,
) -> dict[str, Any]:
    """Execute brain-update payloads against injected DB functions.

    The late-bound function arguments keep this module decoupled from SQLite
    so unit tests can inject fakes.

    When `decay_fn` is supplied it is called exactly once per ingestion batch,
    after every payload has been applied, with the ids this batch touched. That
    keeps "one chat turn == one decay pass" instead of decaying per boost.
    """
    summary: dict[str, Any] = {
        "blocks_found": 0,
        "new_nodes": [],
        "boosted_nodes": [],
        "new_edges": [],
        "decayed_nodes": 0,
        "errors": [],
    }
    payloads = extract_brain_updates(raw_text or "")
    summary["blocks_found"] = len(payloads)
    # Count syntactically-present but unparseable blocks as errors.
    raw_blocks = len(BRAIN_UPDATE_RE.findall(raw_text or ""))
    if raw_blocks > len(payloads):
        summary["errors"].append(
            f"{raw_blocks - len(payloads)} malformed brain-update block(s) skipped"
        )

    for data in payloads:
        for n in data.get("new_nodes") or []:
            if not isinstance(n, dict):
                summary["errors"].append(f"invalid new_nodes entry skipped: {n!r}")
                continue
            nid = _norm_id(n.get("id"))
            if not nid:
                summary["errors"].append(f"new_nodes entry missing id skipped: {n!r}")
                continue
            try:
                upsert_node_fn(
                    {
                        "id": nid,
                        "label": n.get("label") or nid,
                        "category": n.get("category") or "topic",
                        "weight": n.get("weight", 1.0),
                        "summary": n.get("summary") or "",
                    }
                )
                summary["new_nodes"].append(nid)
            except Exception as exc:  # keep ingesting remaining entries
                summary["errors"].append(f"new_node {nid!r} failed: {exc}")
        for nid_raw in data.get("boost_nodes") or []:
            nid = _norm_id(nid_raw)
            if not nid:
                continue
            try:
                updated = boost_node_fn(nid, 0.5)
                if updated is None:
                    summary["errors"].append(f"boost target not found: {nid!r}")
                else:
                    summary["boosted_nodes"].append(nid)
            except Exception as exc:
                summary["errors"].append(f"boost {nid!r} failed: {exc}")
        for e in data.get("new_edges") or []:
            if not isinstance(e, dict):
                summary["errors"].append(f"invalid new_edges entry skipped: {e!r}")
                continue
            s, t = _norm_id(e.get("source")), _norm_id(e.get("target"))
            rel = str(e.get("relation") or "related_to")
            if not s or not t:
                summary["errors"].append(f"edge missing endpoints skipped: {e!r}")
                continue
            try:
                add_edge_fn(s, t, rel)
                summary["new_edges"].append(f"{s}->{t} [{rel}]")
            except Exception as exc:
                summary["errors"].append(f"edge {s!r}->{t!r} failed: {exc}")

    # 一次套用、一次衰減：排除本批次碰過的節點，其餘 topic/skill 微幅淡出。
    touched = list(dict.fromkeys(summary["new_nodes"] + summary["boosted_nodes"]))
    if decay_fn is not None and touched:
        try:
            summary["decayed_nodes"] = int(decay_fn(touched) or 0)
        except Exception as exc:
            summary["errors"].append(f"decay failed: {exc}")
    return summary
