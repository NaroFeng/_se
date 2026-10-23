"""樓層資訊 API：樓層 CRUD、按鈕座標特徵、跨樓層路徑規劃。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Floor, FloorButtonFeature
from ..schemas import (
    ButtonFeatureCreate,
    ButtonFeatureRead,
    FloorCreate,
    FloorRead,
    FloorRoutePlan,
    FloorUpdate,
)
from ..services.floor_service import floor_exists, get_floor_by_code, require_floor
from ..services.robot_state import robot_state_cache

router = APIRouter(prefix="/floors", tags=["樓層資訊 Floors"])


# =====================================================================
# 查詢
# =====================================================================
@router.get("", response_model=list[FloorRead], summary="取得所有樓層清單")
def list_floors(
    db: Session = Depends(get_db),
    active_only: bool = Query(False, description="僅回傳啟用中的樓層"),
    has_elevator: Optional[bool] = Query(None, description="依是否有電梯篩選"),
    keyword: Optional[str] = Query(None, description="依樓層代號/名稱模糊搜尋"),
) -> list[Floor]:
    """依照樓層高度由低到高（地下 B2 → 5F）回傳全部樓層。"""
    stmt = select(Floor)
    if active_only:
        stmt = stmt.where(Floor.is_active.is_(True))
    if has_elevator is not None:
        stmt = stmt.where(Floor.has_elevator.is_(has_elevator))
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(Floor.floor_code.ilike(pattern) | Floor.name.ilike(pattern))
    stmt = stmt.order_by(Floor.floor_index.asc(), Floor.sort_order.asc())

    return list(db.execute(stmt).scalars().all())


@router.get("/active", response_model=dict, summary="取得機器人目前所在樓層")
def get_active_floor(db: Session = Depends(get_db)) -> dict[str, Any]:
    """先從狀態快取取得 current_floor，再回資料庫補齊完整樓層資訊。"""
    snapshot = robot_state_cache.snapshot()
    current_code: Optional[str] = snapshot.get("current_floor")

    floor: Optional[Floor] = None
    if current_code:
        floor = get_floor_by_code(db, current_code)
    if floor is None:
        floor = db.execute(
            select(Floor).where(Floor.is_active.is_(True)).order_by(Floor.floor_index.asc()).limit(1)
        ).scalar_one_or_none()

    return {
        "floor": FloorRead.model_validate(floor).model_dump(mode="json") if floor else None,
        "robot_online": snapshot.get("online", False),
        "source": "heartbeat" if current_code else "fallback",
        "fsm_state": snapshot.get("fsm_state"),
    }


@router.get("/route/plan", response_model=FloorRoutePlan, summary="跨樓層路徑規劃")
def plan_route(
    from_floor: str = Query(..., alias="from", examples=["1F"], description="出發樓層代號"),
    to_floor: str = Query(..., alias="to", examples=["5F"], description="目標樓層代號"),
    db: Session = Depends(get_db),
) -> FloorRoutePlan:
    """依資料庫中的樓層/按鈕設定，產生跨樓層巡檢的步驟清單。"""
    src = require_floor(db, from_floor)
    dst = require_floor(db, to_floor)

    same_floor = src.floor_index == dst.floor_index
    needs_elevator = (not same_floor) and src.has_elevator and dst.has_elevator

    button: Optional[FloorButtonFeature] = None
    if needs_elevator:
        button = db.execute(
            select(FloorButtonFeature).where(
                FloorButtonFeature.floor_code == src.floor_code,
                FloorButtonFeature.elevator_id == src.elevator_id,
                FloorButtonFeature.target_floor_code == dst.floor_code,
                FloorButtonFeature.is_active.is_(True),
            )
        ).scalar_one_or_none()

    steps: list[dict[str, Any]] = []
    if same_floor:
        steps = [
            {"order": 1, "action": "switch_map", "floor": src.floor_code,
             "detail": f"載入地圖 {src.map_name}"},
            {"order": 2, "action": "navigate", "floor": src.floor_code,
             "pose": dst.nav_goal_pose, "detail": "樓層內移動至巡檢點"},
        ]
    else:
        steps = [
            {"order": 1, "action": "navigate", "floor": src.floor_code, "pose": src.waiting_pose,
             "detail": "前往電梯廳等待點"},
            {"order": 2, "action": "detect_button", "floor": src.floor_code,
             "elevator_id": src.elevator_id,
             "button_label": button.button_label if button else dst.floor_code,
             "detail": "視覺比對目標樓層按鈕 (YOLO / Template Matching)"},
            {"order": 3, "action": "press_button", "floor": src.floor_code,
             "button_label": button.button_label if button else dst.floor_code,
             "press_duration_ms": button.press_duration_ms if button else 1200,
             "detail": "按壓並以觸覺感測器二次確認"},
            {"order": 4, "action": "wait_elevator", "floor": src.floor_code,
             "detail": "等待電梯到達並進入 (需回傳門開與車廂內感測)"},
            {"order": 5, "action": "elevator_ride", "from_floor": src.floor_code,
             "to_floor": dst.floor_code, "detail": "搭乘電梯跨樓"},
            {"order": 6, "action": "elevator_exit", "floor": dst.floor_code,
             "pose": dst.dock_pose, "detail": "電梯開門後駛出並停靠"},
            {"order": 7, "action": "switch_map", "from_map": src.map_name, "to_map": dst.map_name,
             "floor": dst.floor_code, "detail": "動態切換 Nav2 地圖與全域定位"},
            {"order": 8, "action": "navigate", "floor": dst.floor_code, "pose": dst.nav_goal_pose,
             "detail": "前往目標樓層巡檢點"},
        ]

    return FloorRoutePlan(
        from_floor=src.floor_code,
        to_floor=dst.floor_code,
        same_floor=same_floor,
        needs_elevator=needs_elevator,
        button_label=button.button_label if button else None,
        from_floor_info=FloorRead.model_validate(src),
        to_floor_info=FloorRead.model_validate(dst),
        steps=steps,
    )


@router.get("/stats/count", response_model=dict, summary="樓層數量統計")
def floor_stats(db: Session = Depends(get_db)) -> dict[str, int]:
    """小工具：回傳樓層總數與有電梯的樓層數。"""
    total = db.execute(select(func.count(Floor.id))).scalar_one()
    with_elevator = db.execute(
        select(func.count(Floor.id)).where(Floor.has_elevator.is_(True))
    ).scalar_one()
    return {"total_floors": total, "floors_with_elevator": with_elevator}


@router.get("/{floor_code}", response_model=FloorRead, summary="取得單一樓層資訊")
def get_floor(floor_code: str, db: Session = Depends(get_db)) -> Floor:
    return require_floor(db, floor_code)


# =====================================================================
# 新增 / 更新 / 刪除
# =====================================================================
@router.post("", response_model=FloorRead, status_code=status.HTTP_201_CREATED, summary="新增樓層")
def create_floor(payload: FloorCreate, db: Session = Depends(get_db)) -> Floor:
    if floor_exists(db, payload.floor_code):
        raise HTTPException(status_code=409, detail=f"樓層已存在：{payload.floor_code}")

    floor = Floor(**payload.model_dump())
    db.add(floor)
    db.commit()
    db.refresh(floor)
    return floor


@router.put("/{floor_code}", response_model=FloorRead, summary="更新樓層（部分更新）")
@router.patch("/{floor_code}", response_model=FloorRead, summary="更新樓層（部分更新）")
def update_floor(floor_code: str, payload: FloorUpdate, db: Session = Depends(get_db)) -> Floor:
    floor = require_floor(db, floor_code)

    data = payload.model_dump(exclude_unset=True)
    new_code = data.pop("floor_code", None)
    if new_code and new_code != floor.floor_code:
        if floor_exists(db, new_code):
            raise HTTPException(status_code=409, detail=f"樓層代號已存在：{new_code}")
        floor.floor_code = new_code

    for key, value in data.items():
        setattr(floor, key, value)

    db.commit()
    db.refresh(floor)
    return floor


@router.delete("/{floor_code}", status_code=status.HTTP_204_NO_CONTENT, summary="刪除樓層")
def delete_floor(floor_code: str, db: Session = Depends(get_db)) -> Response:
    floor = require_floor(db, floor_code)
    db.delete(floor)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =====================================================================
# 電梯按鈕座標特徵
# =====================================================================
@router.get("/{floor_code}/buttons", response_model=list[ButtonFeatureRead],
            summary="取得該樓層的電梯按鈕特徵")
def list_buttons(
    floor_code: str,
    db: Session = Depends(get_db),
    elevator_id: Optional[str] = Query(None, description="電梯編號"),
    active_only: bool = Query(True, description="僅回傳啟用中的按鈕"),
) -> list[FloorButtonFeature]:
    require_floor(db, floor_code)

    stmt = select(FloorButtonFeature).where(FloorButtonFeature.floor_code == floor_code)
    if elevator_id:
        stmt = stmt.where(FloorButtonFeature.elevator_id == elevator_id)
    if active_only:
        stmt = stmt.where(FloorButtonFeature.is_active.is_(True))
    stmt = stmt.order_by(FloorButtonFeature.button_label.asc())

    return list(db.execute(stmt).scalars().all())


@router.post("/{floor_code}/buttons", response_model=ButtonFeatureRead,
             status_code=status.HTTP_201_CREATED, summary="新增/更新該樓層的電梯按鈕特徵")
def upsert_button(
    floor_code: str,
    payload: ButtonFeatureCreate,
    db: Session = Depends(get_db),
) -> FloorButtonFeature:
    require_floor(db, floor_code)

    data = payload.model_dump()
    data.pop("floor_code", None)
    elevator_id = data.pop("elevator_id", "E1")

    button = db.execute(
        select(FloorButtonFeature).where(
            FloorButtonFeature.floor_code == floor_code,
            FloorButtonFeature.elevator_id == elevator_id,
            FloorButtonFeature.button_label == payload.button_label,
        )
    ).scalar_one_or_none()

    if button is None:
        button = FloorButtonFeature(floor_code=floor_code, elevator_id=elevator_id, **data)
        db.add(button)
    else:
        for key, value in data.items():
            setattr(button, key, value)
        button.is_active = True

    db.commit()
    db.refresh(button)
    return button


@router.delete("/{floor_code}/buttons/{button_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="刪除電梯按鈕特徵")
def delete_button(floor_code: str, button_id: int, db: Session = Depends(get_db)) -> Response:
    button = db.get(FloorButtonFeature, button_id)
    if button is None or button.floor_code != floor_code:
        raise HTTPException(status_code=404, detail=f"查無按鈕特徵：{button_id}")
    db.delete(button)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)