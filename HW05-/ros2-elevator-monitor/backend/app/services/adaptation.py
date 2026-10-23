"""中央大腦：按鈕參數線上自適應學習（Online Parameter Adaptation）。

設計理念
--------
後端與資料庫是「中央知識與策略伺服器（Central Knowledge & Policy Server）」。
每台機器人（不同測試機台或實機）在執行巡檢時會回報按鈕事件的實測結果，
後端據此自動更新 `floor_button_features` 的參數，讓**下一台機器人**
或**同一台機器人的下一次執行**直接受惠——無需重新調參。

學習規則（依循奧卡姆剃刀：只從最具診斷性的兩個訊號學習）
------------------------------------------------------------
1. **需要重試才成功**（`detail.attempt > 1`）
   代表按壓過短或視覺門檻過嚴。
   → `press_duration_ms` 階梯式調高 `+150ms`（上限 2500ms）
   → `confidence_threshold` 以 EMA 下調（放寬），但不小於 0.65

2. **視覺信心度貼近門檻**（confidence < threshold + 0.05 且通過）
   代表條件 borderline，略微收緊門檻可減少後續重試成本。
   → `confidence_threshold` 以 EMA 上調，但不大於 0.90

3. **一次就成功且信心度充裕**（attempt == 0 且 confidence >= threshold + 0.15）
   代表條件良好，可稍微放寬以提升容錯。
   → `confidence_threshold` 以 EMA 下調，但不小於 0.65

EMA 公式：`new = old + alpha * (observed - old)`，alpha 預設 0.25。
所有調整都受安全範圍夾限，避免學習發散。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FloorButtonFeature

logger = logging.getLogger(__name__)

# ---------------- 安全範圍 ----------------
MIN_THRESHOLD = 0.65          # 門檻下限（再低容易誤判）
MAX_THRESHOLD = 0.90          # 門檻上限（再高容易失敗）
MIN_PRESS_MS = 800            # 按壓下限（太短觸發不了）
MAX_PRESS_MS = 2500           # 按壓上限（太久可能誤觸鄰鈕）
PRESS_STEP_MS = 150           # 階梯式調高步長
EMA_ALPHA = 0.25              # EMA 權重
PRESS_DECAY_SOFT_MS = 30      # 成功時輕微收斂步長

# ---------------- 基準值（Decay 收斂目標）----------------
# 長期執行時參數應回到這些基準，而不是卡在極限值。
# 連續成功時朝此方向緩慢收斂，形成「雙向平衡」以避免單向漂移。
BASE_PRESS_MS = 1200          # 按壓時間基準值
BASE_THRESHOLD = 0.75         # 視覺門檻基準值
RECOVERY_ALPHA = 0.10         # 收斂時的 EMA 權重（比常規更慢，避免震盪）

# 觸發學習的信心度邊際
BORDERLINE_MARGIN = 0.05      # 低於門檻 + 5% 視為 borderline
COMFIDENT_MARGIN = 0.15       # 高於門檻 + 15% 視為條件充裕


@dataclass
class AdaptationResult:
    """一次學習的結果摘要。"""

    applied: bool
    floor_code: Optional[str] = None
    button_label: Optional[str] = None
    reason: str = ""

    press_before: Optional[int] = None
    press_after: Optional[int] = None
    threshold_before: Optional[float] = None
    threshold_after: Optional[float] = None

    def to_detail(self) -> dict[str, Any]:
        """轉成可寫入巡檢日誌 detail 的格式。"""
        if not self.applied:
            return {}
        return {
            "central_brain": {
                "message": "中央大腦已根據本次經驗更新按鈕特徵參數",
                "floor_code": self.floor_code,
                "button_label": self.button_label,
                "reason": self.reason,
                "press_duration_ms": {
                    "before": self.press_before, "after": self.press_after,
                },
                "confidence_threshold": {
                    "before": self.threshold_before,
                    "after": round(self.threshold_after, 4) if self.threshold_after else None,
                },
            }
        }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _ema(old: float, observed: float, alpha: float = EMA_ALPHA) -> float:
    """指數移動平均。"""
    return old + alpha * (observed - old)


def _decay_press(current: int, decay_step: int = PRESS_STEP_MS) -> int:
    """讓按壓時間朝基準值收斂（Decay），避免長期單向漂移。

    使用 EMA 而非固定減法，讓離基準越遠時收斂越明顯、越近時越溫和，
    避免在基準值附近來回震盪。
    """
    if current <= BASE_PRESS_MS:
        return BASE_PRESS_MS
    gap = current - BASE_PRESS_MS
    step = max(decay_step, int(gap * RECOVERY_ALPHA * 2))
    return int(max(BASE_PRESS_MS, current - step))


def _extract_press_ms(detail: dict[str, Any], fallback: int) -> int:
    """從 detail 取得實際使用的按壓時間。"""
    for key in ("press_duration_ms", "press_ms"):
        value = detail.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, dict) and isinstance(value.get("used"), (int, float)):
            return int(value["used"])
    tactile = detail.get("tactile")
    if isinstance(tactile, dict) and isinstance(tactile.get("press_duration_ms"), (int, float)):
        return int(tactile["press_duration_ms"])
    return fallback


def learn_from_button_event(
    db: Session,
    *,
    floor_code: Optional[str],
    target_floor_code: Optional[str],
    detail: dict[str, Any],
    event_status: str,
) -> AdaptationResult:
    """依按鈕事件結果更新對應按鈕的特徵參數。

    這是中央大腦的核心閉環入口：由 `POST /api/v1/inspections/logs[/batch]`
    在寫入日誌時呼叫。

    Parameters
    ----------
    floor_code: 事件發生的樓層（按鈕所在樓層）
    target_floor_code: 按鈕目標樓層
    detail: 事件 detail（需含 vision_confidence / threshold / attempt）
    event_status: 'success' / 'warning' / 'failed'
    """
    if not floor_code:
        return AdaptationResult(applied=False, reason="事件未提供樓層")

    detail = detail or {}

    # ---------- 取出觀測值 ----------
    attempt = int(detail.get("attempt") or 0)
    confidence = detail.get("vision_confidence")
    threshold_used = detail.get("vision_threshold")

    # 必須有實際觀測到視覺信心度才學習（避免誤觸無效學習）
    if confidence is None or not isinstance(confidence, (int, float)):
        return AdaptationResult(applied=False, reason="事件未包含視覺信心度")

    confidence = float(confidence)
    if threshold_used is None or not isinstance(threshold_used, (int, float)):
        threshold_used = _assume_threshold(confidence)
    threshold_used = float(threshold_used)

    # ---------- 找出對應按鈕特徵 ----------
    label = detail.get("button_label") or target_floor_code
    feature = _find_feature(db, floor_code, target_floor_code, label)
    if feature is None:
        return AdaptationResult(
            applied=False, floor_code=floor_code, button_label=label,
            reason="查無對應的按鈕特徵",
        )

    # ---------- 判定學習方向 ----------
    press_before = int(feature.press_duration_ms)
    threshold_before = float(feature.confidence_threshold)

    new_press = press_before
    new_threshold = threshold_before
    reason = ""

    if event_status != "success":
        # 失敗事件：保守加長按壓時間、放寬門檻
        new_press = min(MAX_PRESS_MS, press_before + PRESS_STEP_MS)
        new_threshold = _clamp(_ema(threshold_before, max(0.65, threshold_before - 0.05)),
                               MIN_THRESHOLD, MAX_THRESHOLD)
        reason = "按鈕事件失敗 → 加長按壓並適度放寬門檻"

    elif attempt > 1:
        # 需要重試才成功：門檻過嚴或按壓過短
        new_press = min(MAX_PRESS_MS, press_before + PRESS_STEP_MS)
        new_threshold = _clamp(_ema(threshold_before, max(0.65, confidence - BORDERLINE_MARGIN)),
                               MIN_THRESHOLD, MAX_THRESHOLD)
        reason = f"重試 {attempt - 1} 次後才成功 → 加長按壓並放寬門檻"

    elif confidence < threshold_used + BORDERLINE_MARGIN:
        # borderline 通過：條件不穩定，適度收緊門檻
        new_threshold = _clamp(_ema(threshold_before, confidence + BORDERLINE_MARGIN),
                               MIN_THRESHOLD, MAX_THRESHOLD)
        reason = "視覺信心度貼近門檻 → 適度收緊門檻以穩定判定"

    elif attempt == 0 and confidence >= threshold_used + CONFIDENT_MARGIN:
        # 條件充裕：放寬門檻提升容錯，並讓按壓時間緩慢收斂回基準值
        new_threshold = _clamp(_ema(threshold_before, max(MIN_THRESHOLD, threshold_used - 0.02)),
                               MIN_THRESHOLD, MAX_THRESHOLD)
        if press_before > BASE_PRESS_MS:
            new_press = _decay_press(press_before)
            reason = "一次即成功且信心度充裕 → 放寬門檻並讓按壓時間收斂回基準"
        else:
            reason = "一次即成功且信心度充裕 → 放寬門檻提升容錯"

    elif attempt == 1 and confidence >= threshold_used + BORDERLINE_MARGIN:
        # 首次即成功且有一定餘裕：雙向平衡，防止參數長期單向漂移
        if press_before > BASE_PRESS_MS:
            new_press = _decay_press(press_before, decay_step=PRESS_DECAY_SOFT_MS)
            reason = "首次即成功且有餘裕 → 按壓時間輕微收斂（防參數漂移）"
        elif threshold_before > BASE_THRESHOLD:
            new_threshold = _clamp(_ema(threshold_before, BASE_THRESHOLD, RECOVERY_ALPHA),
                                   MIN_THRESHOLD, MAX_THRESHOLD)
            reason = "首次即成功且有餘裕 → 門檻緩慢回歸基準值"
        else:
            return AdaptationResult(
                applied=False, floor_code=floor_code, button_label=feature.button_label,
                reason="首次即成功，且參數已在基準值附近，無需調整",
            )

    else:
        return AdaptationResult(
            applied=False, floor_code=floor_code, button_label=feature.button_label,
            reason="觀測值落在健康區間，無需調整",
        )

    # ---------- 夾限並套用 ----------
    new_press = int(_clamp(new_press, MIN_PRESS_MS, MAX_PRESS_MS))
    new_threshold = _clamp(new_threshold, MIN_THRESHOLD, MAX_THRESHOLD)

    if new_press == press_before and abs(new_threshold - threshold_before) < 1e-6:
        return AdaptationResult(
            applied=False, floor_code=floor_code, button_label=feature.button_label,
            reason="調整後參數與原值相同（已達安全範圍邊界）",
        )

    feature.press_duration_ms = new_press
    feature.confidence_threshold = round(new_threshold, 4)
    db.flush()

    result = AdaptationResult(
        applied=True,
        floor_code=floor_code,
        button_label=feature.button_label,
        reason=reason,
        press_before=press_before,
        press_after=new_press,
        threshold_before=threshold_before,
        threshold_after=new_threshold,
    )
    logger.info(
        "中央大腦學習：%s/%s 按壓 %d→%dms、門檻 %.3f→%.3f（%s）",
        floor_code, feature.button_label, press_before, new_press,
        threshold_before, new_threshold, reason,
    )
    return result


# =====================================================================
# 內部工具
# =====================================================================
def _assume_threshold(confidence: float) -> float:
    """未記錄實際門檻時，以預設值 0.75 推估。"""
    return 0.75


def _find_feature(
    db: Session,
    floor_code: str,
    target_floor_code: Optional[str],
    button_label: Optional[str],
) -> Optional[FloorButtonFeature]:
    """依樓層 + 目標樓層（或按鈕文字）查出按鈕特徵。"""
    if button_label:
        feature = db.execute(
            select(FloorButtonFeature).where(
                FloorButtonFeature.floor_code == floor_code,
                FloorButtonFeature.button_label == button_label,
            )
        ).scalars().first()
        if feature:
            return feature

    if target_floor_code:
        return db.execute(
            select(FloorButtonFeature).where(
                FloorButtonFeature.floor_code == floor_code,
                FloorButtonFeature.target_floor_code == target_floor_code,
            )
        ).scalars().first()

    return None
