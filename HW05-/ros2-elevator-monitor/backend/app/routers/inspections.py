"""巡檢紀錄日誌 API：日誌寫入（Bridge/機器人上報）、查詢、統計。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import FloorButtonFeature, InspectionLog
from ..services import adaptation
from ..schemas import (
    InspectionLogBatch,
    InspectionLogCreate,
    InspectionLogPage,
    InspectionLogRead,
    InspectionSummary,
    InspectionTaskSummary,
)
from ..services.common_types import EventType
from ..services.adaptation import learn_from_button_event
from ..services.floor_service import ensure_floor_exists

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/inspections", tags=["巡檢紀錄 Inspections"])


def _validate_floor_codes(db: Session, *codes: Optional[str]) -> None:
    """檢查樓層代號是否存在（資料庫有 FK 約束，先擋掉錯誤資料）。"""
    for code in {c for c in codes if c}:
        ensure_floor_exists(db, code)


def _build_log(payload: InspectionLogCreate) -> InspectionLog:
    data = payload.model_dump()
    # 多餘欄位（extra="allow" 收集）併入 detail，避免遺失診斷資訊
    extra = data.pop("__pydantic_extra__", None) or {}
    detail = data.get("detail") or {}
    detail.update(extra)
    data["detail"] = detail

    data["inspection_uuid"] = data["inspection_uuid"] or uuid.uuid4()
    data["occurred_at"] = data["occurred_at"] or datetime.now(timezone.utc)
    data["detail"] = data["detail"] or {}
    return InspectionLog(**data)


def _maybe_adapt(db: Session, log: InspectionLog) -> dict[str, Any]:
    """中央大腦閉環：按鈕事件觸發線上參數學習。

    只對 button_detect / button_press 事件進行學習，
    並把學習結果寫回 log.detail，讓日誌保留「誰、何時、因何調整了參數」。
    """
    if log.event_type not in (EventType.BUTTON_DETECT, EventType.BUTTON_PRESS):
        return {}

    result = learn_from_button_event(
        db,
        floor_code=log.floor_code,
        target_floor_code=log.to_floor_code,
        detail=log.detail or {},
        event_status=log.status,
    )
    if not result.applied:
        return {}

    payload = result.to_detail()
    log.detail = {**(log.detail or {}), **payload}
    return payload


# =====================================================================
# 寫入（ros2-bridge / ROS 2 節點呼叫）
# =====================================================================
@router.post("/logs", response_model=InspectionLogRead, status_code=status.HTTP_201_CREATED,
             summary="寫入單筆巡檢日誌")
def create_log(payload: InspectionLogCreate, db: Session = Depends(get_db)) -> InspectionLog:
    """FSM 每完成一個步驟即上報一筆事件日誌。"""
    _validate_floor_codes(db, payload.floor_code, payload.from_floor_code, payload.to_floor_code)

    log = _build_log(payload)
    db.add(log)
    db.flush()                      # 先 flush 取得 log.id
    adaptation = _maybe_adapt(db, log)   # 中央大腦：線上學習按鈕參數
    db.commit()
    db.refresh(log)
    logger.info("已記錄巡檢事件 %s / %s / %s", log.inspection_uuid, log.event_type, log.status)
    return log


@router.post("/logs/batch", status_code=status.HTTP_201_CREATED, summary="批次寫入巡檢日誌")
def create_logs_batch(payload: InspectionLogBatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    """橋接節點離線恢復或高頻事件時可批次補登。"""
    logs: list[InspectionLog] = []
    for item in payload.logs:
        _validate_floor_codes(db, item.floor_code, item.from_floor_code, item.to_floor_code)
        logs.append(_build_log(item))

    db.add_all(logs)
    db.flush()

    # 中央大腦：批次中所有按鈕事件一併學習
    adaptations: list[dict[str, Any]] = []
    for log in logs:
        result = _maybe_adapt(db, log)
        if result:
            adaptations.append(result)

    db.commit()

    response: dict[str, Any] = {
        "accepted": len(logs),
        "inspection_uuids": sorted({str(log.inspection_uuid) for log in logs}),
    }
    if adaptations:
        response["adaptations"] = adaptations
        logger.info("中央大腦已依 %s 筆事件更新按鈕參數", len(adaptations))
    return response


# =====================================================================
# 查詢
# =====================================================================
@router.get("/logs", response_model=InspectionLogPage, summary="查詢巡檢日誌（可篩選/分頁）")
def list_logs(
    db: Session = Depends(get_db),
    inspection_uuid: Optional[str] = Query(None, description="只查特定巡檢任務"),
    robot_name: Optional[str] = Query(None, description="機器人名稱"),
    event_type: Optional[str] = Query(None, description="事件類型"),
    status_filter: Optional[str] = Query(None, alias="status", description="事件狀態"),
    log_level: Optional[str] = Query(None, description="日誌等級"),
    floor_code: Optional[str] = Query(None, description="事件所在樓層"),
    keyword: Optional[str] = Query(None, description="訊息內容模糊搜尋"),
    start_time: Optional[datetime] = Query(None, description="起始時間 (ISO8601)"),
    end_time: Optional[datetime] = Query(None, description="結束時間 (ISO8601)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    order_desc: bool = Query(True, description="依時間由新到舊"),
) -> InspectionLogPage:
    def _filter(stmt: Select) -> Select:
        if inspection_uuid:
            try:
                stmt = stmt.where(InspectionLog.inspection_uuid == uuid.UUID(inspection_uuid))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="inspection_uuid 格式錯誤") from exc
        if robot_name:
            stmt = stmt.where(InspectionLog.robot_name == robot_name)
        if event_type:
            stmt = stmt.where(InspectionLog.event_type == event_type)
        if status_filter:
            stmt = stmt.where(InspectionLog.status == status_filter)
        if log_level:
            stmt = stmt.where(InspectionLog.log_level == log_level)
        if floor_code:
            stmt = stmt.where(
                (InspectionLog.floor_code == floor_code)
                | (InspectionLog.from_floor_code == floor_code)
                | (InspectionLog.to_floor_code == floor_code)
            )
        if keyword:
            stmt = stmt.where(InspectionLog.message.ilike(f"%{keyword}%"))
        if start_time:
            stmt = stmt.where(InspectionLog.occurred_at >= start_time)
        if end_time:
            stmt = stmt.where(InspectionLog.occurred_at <= end_time)
        return stmt

    total = db.execute(_filter(select(func.count(InspectionLog.id)))).scalar_one()
    rows = db.execute(
        _filter(select(InspectionLog))
        .order_by(InspectionLog.occurred_at.desc() if order_desc else InspectionLog.occurred_at.asc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return InspectionLogPage(total=total, limit=limit, offset=offset,
                             items=[InspectionLogRead.model_validate(r) for r in rows])


@router.get("/latest", response_model=list[InspectionLogRead], summary="取得最新巡檢動態")
def latest_logs(
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=200),
) -> list[InspectionLog]:
    stmt = select(InspectionLog).order_by(InspectionLog.occurred_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


@router.get("/tasks", response_model=list[InspectionTaskSummary], summary="巡檢任務彙總清單")
def list_tasks(
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
) -> list[InspectionTaskSummary]:
    """讀取 v_inspection_summary 檢視。"""
    rows = db.execute(
        text(
            "SELECT inspection_uuid, robot_name, task_name, started_at, finished_at, "
            "event_count, error_count, has_failed, all_success, final_floor_code "
            "FROM v_inspection_summary ORDER BY started_at DESC LIMIT :limit"
        ),
        {"limit": limit},
    ).mappings().all()
    return [InspectionTaskSummary(**dict(row)) for row in rows]


@router.get("/summary", response_model=InspectionSummary, summary="巡檢統計摘要")
def summary(
    db: Session = Depends(get_db),
    days: int = Query(7, ge=1, le=365, description="統計區間天數"),
) -> InspectionSummary:
    """提供儀表板用的成功率與事件分布統計。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    total_events = db.execute(
        select(func.count(InspectionLog.id)).where(InspectionLog.occurred_at >= since)
    ).scalar_one()
    error_events = db.execute(
        select(func.count(InspectionLog.id)).where(
            InspectionLog.occurred_at >= since, InspectionLog.log_level == "ERROR"
        )
    ).scalar_one()

    by_event_type = {
        row.event_type: row.count
        for row in db.execute(
            select(InspectionLog.event_type, func.count(InspectionLog.id).label("count"))
            .where(InspectionLog.occurred_at >= since)
            .group_by(InspectionLog.event_type)
        ).all()
    }
    by_status = {
        row.status: row.count
        for row in db.execute(
            select(InspectionLog.status, func.count(InspectionLog.id).label("count"))
            .where(InspectionLog.occurred_at >= since)
            .group_by(InspectionLog.status)
        ).all()
    }
    by_floor = {
        (row.floor_code or "unknown"): row.count
        for row in db.execute(
            select(InspectionLog.floor_code, func.count(InspectionLog.id).label("count"))
            .where(InspectionLog.occurred_at >= since)
            .group_by(InspectionLog.floor_code)
        ).all()
    }

    task_rows = [
        dict(row)
        for row in db.execute(
            text(
                "SELECT inspection_uuid, robot_name, task_name, started_at, finished_at, "
                "event_count, error_count, has_failed, all_success, final_floor_code "
                "FROM v_inspection_summary"
            )
        ).mappings().all()
        if row["started_at"] >= since
    ]

    total_inspections = len(task_rows)
    success_inspections = sum(1 for r in task_rows if r["all_success"])
    failed_inspections = sum(1 for r in task_rows if r["has_failed"])
    success_rate = round(success_inspections / total_inspections * 100, 2) if total_inspections else 0.0

    return InspectionSummary(
        days=days,
        total_events=total_events,
        total_inspections=total_inspections,
        success_inspections=success_inspections,
        failed_inspections=failed_inspections,
        error_events=error_events,
        success_rate=success_rate,
        by_event_type=by_event_type,
        by_status=by_status,
        by_floor=by_floor,
    )


@router.get("/policy", summary="中央大腦目前策略（儀表板用）")
def central_policy(
    db: Session = Depends(get_db),
    floor_code: Optional[str] = Query(None, description="指定樓層；未指定則回傳全部"),
    only_learned: bool = Query(False, description="僅顯示曾被學習調整過的按鈕"),
    limit: int = Query(60, ge=1, le=300),
) -> dict[str, Any]:
    """回傳中央大腦目前持有的按鈕策略（press_duration_ms / confidence_threshold）。

    供前端儀表板顯示「參數因重試而自動演進」的過程；
    每筆資料的 updated_at 對應該按鈕最後一次被學習更新的時間。
    """
    base_q = select(FloorButtonFeature).order_by(
        FloorButtonFeature.floor_code, FloorButtonFeature.button_label
    )
    if floor_code:
        base_q = base_q.where(FloorButtonFeature.floor_code == floor_code)
    if only_learned:
        # updated_at 明顯晚於 created_at 代表曾被學習更新過
        base_q = base_q.where(FloorButtonFeature.updated_at > FloorButtonFeature.created_at)
    base_q = base_q.limit(limit)

    items: list[dict[str, Any]] = []
    learned_count = 0

    for f in db.execute(base_q).scalars().all():
        # 找出此按鈕最近一次學習紀錄（作為「更新來源」）
        last_brain = db.execute(
            select(InspectionLog)
            .where(
                InspectionLog.event_type.in_(
                    (EventType.BUTTON_PRESS, EventType.BUTTON_DETECT)
                ),
                InspectionLog.floor_code == f.floor_code,
                InspectionLog.detail.has_key("central_brain"),
            )
            .order_by(InspectionLog.occurred_at.desc())
            .limit(1)
        ).scalars().first()

        is_learned = last_brain is not None
        if is_learned:
            learned_count += 1

        source = "seed（初始值）"
        reason = None
        if is_learned:
            brain = (last_brain.detail or {}).get("central_brain", {})
            source = f"由 {last_brain.robot_name} 經驗學習更新"
            reason = brain.get("reason")

        press = int(f.press_duration_ms)
        items.append({
            "floor_code": f.floor_code,
            "button_label": f.button_label,
            "target_floor_code": f.target_floor_code,
            "press_duration_ms": press,
            "confidence_threshold": round(float(f.confidence_threshold), 4),
            # 與基準值的差距，顯示收斂進度
            "press_drift": press - adaptation.BASE_PRESS_MS,
            "threshold_drift": round(float(f.confidence_threshold) - adaptation.BASE_THRESHOLD, 4),
            "at_base": press <= adaptation.BASE_PRESS_MS,
            "learned": is_learned,
            "policy_source": source,
            "reason": reason,
            "updated_at": f.updated_at,
            "source_event_id": last_brain.id if last_brain else None,
        })

    return {
        "total": len(items),
        "learned_count": learned_count,
        "base_press_ms": adaptation.BASE_PRESS_MS,
        "base_threshold": adaptation.BASE_THRESHOLD,
        "safe_range": {
            "press_ms": [adaptation.MIN_PRESS_MS, adaptation.MAX_PRESS_MS],
            "threshold": [adaptation.MIN_THRESHOLD, adaptation.MAX_THRESHOLD],
        },
        "items": items,
    }


@router.get("/adaptations", summary="中央大腦按鈕參數學習紀錄")
def list_adaptations(
    db: Session = Depends(get_db),
    floor_code: Optional[str] = Query(None, description="依樓層篩選"),
    limit: int = Query(30, ge=1, le=200),
) -> dict[str, Any]:
    """查詢中央大腦自動調整按鈕參數的歷史紀錄。

    資料來源為巡檢日誌中 `detail.central_brain` 欄位，
    因此每一筆學習都可回溯到觸發它的原始事件。
    """
    # 用 ? 運算子判斷「鍵是否存在」；不能用 @>，
    # 因為 @> '{"central_brain": {}}' 要求該鍵的值恰好為空物件，
    # 而實際儲存的是有內容的物件，會查不到任何結果。
    stmt = select(InspectionLog).where(
        InspectionLog.detail.has_key("central_brain")
    )
    if floor_code:
        stmt = stmt.where(InspectionLog.floor_code == floor_code)
    stmt = stmt.order_by(InspectionLog.occurred_at.desc()).limit(limit)

    items = []
    for log in db.execute(stmt).scalars().all():
        brain = (log.detail or {}).get("central_brain", {})
        items.append({
            "occurred_at": log.occurred_at,
            "robot_name": log.robot_name,
            "floor_code": brain.get("floor_code") or log.floor_code,
            "button_label": brain.get("button_label"),
            "reason": brain.get("reason"),
            "press_duration_ms": brain.get("press_duration_ms"),
            "confidence_threshold": brain.get("confidence_threshold"),
            "source_event_id": log.id,
        })

    return {"total": len(items), "items": items}


@router.get("/logs/{log_id}", response_model=InspectionLogRead, summary="取得單筆巡檢日誌")
def get_log(log_id: int, db: Session = Depends(get_db)) -> InspectionLog:
    log = db.get(InspectionLog, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail=f"查無巡檢日誌：{log_id}")
    return log


@router.delete("/logs/{log_id}", status_code=status.HTTP_204_NO_CONTENT, summary="刪除巡檢日誌")
def delete_log(log_id: int, db: Session = Depends(get_db)) -> Response:
    log = db.get(InspectionLog, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail=f"查無巡檢日誌：{log_id}")
    db.delete(log)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)