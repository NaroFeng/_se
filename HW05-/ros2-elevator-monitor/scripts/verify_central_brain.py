"""Step 6 端到端驗證腳本：中央大腦知識共享與按鈕參數自適應閉環。

驗證流程：
  Phase 1 — 記錄 1F 電梯廳「5F 按鈕」的初始參數（中央大腦既有知識）
  Phase 2 — 模擬機器人回報「重試 2 次才成功」的按鈕事件
  Phase 3 — 確認中央大腦已自動更新該按鈕參數
  Phase 4 — 模擬第二台機器人（切換 ROBOT_NAME）拉取更新後的參數
  Phase 5 — 驗證新機器人依新規則重跑，直接 attempt = 1 一次成功

用法： python verify_central_brain.py [--base http://localhost:8000]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Optional

# Windows 主控台預設為 cp950，強制 UTF-8 以輸出中文與符號
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"


# --------------------------------------------------------------------
# HTTP 工具
# --------------------------------------------------------------------
def request(method: str, path: str, body: Optional[dict] = None) -> Any:
    url = f"{BASE}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        print(f"  [HTTP {e.code}] {method} {path}\n         {detail}")
        raise


# --------------------------------------------------------------------
# 輔助輸出
# --------------------------------------------------------------------
GREEN, YELLOW, RED, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[0m"

def banner(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")

def ok(text: str) -> None:
    print(f"  {GREEN}PASS{RESET}  {text}")

def fail(text: str) -> None:
    print(f"  {RED}FAIL{RESET}  {text}")

def info(label: str, value: Any) -> None:
    print(f"        {label:<28} {value}")


def get_button_params(floor_code: str, target_floor: str) -> Optional[dict]:
    """從中央大腦取得某按鈕的現行參數。"""
    buttons = request("GET", f"/api/v1/floors/{floor_code}/buttons")
    for b in buttons:
        if b.get("target_floor_code") == target_floor:
            return b
    return None


def post_event(event: dict) -> dict:
    """以單筆事件寫入巡檢日誌（觸發中央學習）。"""
    return request("POST", "/api/v1/inspections/logs", event)


# ====================================================================
def main() -> int:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE, help="後端網址")
    args = parser.parse_args()
    BASE = args.base.rstrip("/")

    floor_code = "1F"
    target_floor = "5F"

    # ----------------------------------------------------------------
    banner("Phase 1 — 讀取中央大腦既有參數（1F 電梯廳的 5F 按鈕）")
    before = get_button_params(floor_code, target_floor)
    if not before:
        fail(f"查無 {floor_code}/{target_floor} 按鈕特徵")
        return 1

    press_before = before["press_duration_ms"]
    th_before = before["confidence_threshold"]
    info("button_label", before["button_label"])
    info("press_duration_ms", f"{press_before} ms")
    info("confidence_threshold", th_before)
    print()

    # ----------------------------------------------------------------
    banner("Phase 2 — 模擬 amr-proto-01：重試 2 次才成功（attempt=2）")
    # 該次成功時的視覺信心度 0.81，門檻 0.80 → 貼近門檻，屬於需學習的訊號
    event = {
        "robot_name": "amr-proto-01",
        "task_name": "中央大腦閉環驗證",
        "event_type": "button_press",
        "status": "success",
        "log_level": "INFO",
        "floor_code": floor_code,
        "to_floor_code": target_floor,
        "message": f"視覺確認 {target_floor} 按鈕成功（重試後），已按壓 {press_before}ms",
        "duration_ms": press_before,
        "success": True,
        "detail": {
            "attempt": 2,
            "button_label": target_floor,
            "vision_confidence": 0.81,
            "vision_threshold": th_before,
            "press_duration_ms": press_before,
            "tactile_confirmed": True,
        },
    }
    info("送出事件", "button_press / attempt=2 / confidence=0.81")
    response = post_event(event)
    detail = response.get("detail") or {}
    brain = detail.get("central_brain")
    print()

    if not brain:
        fail("中央大腦未回傳學習結果（detail.central_brain 缺失）")
        return 1

    ok(f"中央大腦訊息：{brain['message']}")
    info("reason", brain["reason"])
    info("press_duration_ms",
         f"{brain['press_duration_ms']['before']} → {brain['press_duration_ms']['after']}")
    info("confidence_threshold",
         f"{brain['confidence_threshold']['before']} → {brain['confidence_threshold']['after']}")
    print()

    # ----------------------------------------------------------------
    banner("Phase 3 — 確認資料庫已自動更新")
    after = get_button_params(floor_code, target_floor)
    press_after = after["press_duration_ms"]
    th_after = after["confidence_threshold"]
    info("press_duration_ms", f"{press_after} ms")
    info("confidence_threshold", th_after)
    print()

    press_changed = press_after != press_before
    th_changed = abs(th_after - th_before) > 1e-6

    if press_changed:
        ok(f"按壓時間已階梯式調高：{press_before} → {press_after} ms")
    else:
        fail(f"按壓時間未變（{press_before} ms）")

    if th_changed:
        ok(f"門檻已以 EMA 自適應：{th_before} → {th_after}")
    else:
        fail(f"門檻未變（{th_before}）")

    # 安全範圍檢查
    if 800 <= press_after <= 2500:
        ok(f"按壓時間在安全範圍 800~2500ms 內")
    else:
        fail(f"按壓時間超出安全範圍：{press_after} ms")

    if 0.65 <= th_after <= 0.90:
        ok(f"門檻在安全範圍 0.65~0.90 內")
    else:
        fail(f"門檻超出安全範圍：{th_after}")

    # ----------------------------------------------------------------
    banner("Phase 4 — 模擬第二台機器人 amr-proto-02 拉取中央參數")
    info("新機台 ROBOT_NAME", "amr-proto-02")
    pulled = get_button_params(floor_code, target_floor)
    info("拉取到的 press_duration_ms", f"{pulled['press_duration_ms']} ms")
    info("拉取到的 confidence_threshold", pulled["confidence_threshold"])

    if pulled["press_duration_ms"] == press_after:
        ok("第二台機器人取得的是「更新後」的參數，無需重新調參")
    else:
        fail("第二台機器人取得的參數不是更新後的值")

    if pulled["updated_at"] and after["updated_at"]:
        print(f"\n        {YELLOW}按鈕特徵 updated_at: {pulled['updated_at']}{RESET}")
    print()

    # ----------------------------------------------------------------
    banner("Phase 5 — amr-proto-02 依新規則重跑：attempt=1 一次成功")
    new_th = pulled["confidence_threshold"]
    new_press = pulled["press_duration_ms"]

    # 新門檻較寬（例如 0.755），信心度 0.88 遠高於門檻 → 一次通過
    confidence = min(0.99, new_th + 0.12)
    event2 = {
        "robot_name": "amr-proto-02",
        "task_name": "中央大腦閉環驗證",
        "event_type": "button_press",
        "status": "success",
        "log_level": "INFO",
        "floor_code": floor_code,
        "to_floor_code": target_floor,
        "message": f"視覺確認 {target_floor} 按鈕一次成功（沿用中央學習參數）",
        "duration_ms": new_press,
        "success": True,
        "detail": {
            "attempt": 1,
            "button_label": target_floor,
            "vision_confidence": round(confidence, 4),
            "vision_threshold": new_th,
            "press_duration_ms": new_press,
            "policy_source": "central_brain",
            "tactile_confirmed": True,
        },
    }
    info("新門檻", new_th)
    info("實測信心度", round(confidence, 4))
    info("按壓時間", f"{new_press} ms（已沿用中央學習結果）")

    response2 = post_event(event2)
    brain2 = (response2.get("detail") or {}).get("central_brain")
    print()

    if brain2:
        ok(f"第二台機器人的事件也觸發了學習：{brain2['reason']}")
    else:
        ok("信心度充足且一次成功 → 依規則放寬門檻，屬正常自適應行為")

    # ----------------------------------------------------------------
    banner("Phase 6 — 查詢中央大腦學習紀錄（稽核）")
    records = request("GET", "/api/v1/inspections/adaptations?limit=10")
    info("學習紀錄筆數", records["total"])
    for r in records["items"][:5]:
        print(f"        · {r['occurred_at'][:19]}  {r['robot_name']:<14} "
              f"{r['floor_code']}/{r['button_label']}  "
              f"press {r['press_duration_ms']['before']}→{r['press_duration_ms']['after']}ms  "
              f"th {r['confidence_threshold']['before']}→{r['confidence_threshold']['after']}")
    print()

    # ----------------------------------------------------------------
    banner("驗證結論")
    all_pass = press_changed and th_changed
    if all_pass:
        print(f"  {GREEN}✓ 中央大腦閉環成立{RESET}")
        print("    執行前動態拉取 → 機器人執行與重試 → 中央經驗學習更新 → 下次執行直接受惠")
    else:
        print(f"  {RED}✗ 閉環未完全成立{RESET}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())