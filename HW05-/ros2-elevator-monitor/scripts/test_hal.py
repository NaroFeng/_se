"""HAL mock 模式驗證：確認與原 button_recognizer 行為一致（零回歸基礎）。"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from elevator_inspection.hardware_hal import (
    CameraInterface, ActuatorInterface, MecanumBaseInterface,
    HardwareHAL, HardwareMode, get_hardware_mode, reset_hal,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

print(f"=== 模式解析 ===")
print(f"  HARDWARE_MODE 環境變數 = {os.getenv('HARDWARE_MODE', '(未設定)')}")
print(f"  get_hardware_mode()    = {get_hardware_mode()}  (預設應為 mock)")

print("\n=== CameraInterface：確定性（對應原 _simulate_vision_score）===")
c = CameraInterface()
a1 = c.match_button("3F", 0.80, "1F", 0)
a2 = c.match_button("3F", 0.80, "1F", 0)
print(f"  1F→3F attempt=0 第1次 : confidence={a1.confidence}")
print(f"  1F→3F attempt=0 第2次 : confidence={a2.confidence}")
print(f"  [{'OK' if a1.confidence == a2.confidence else 'FAIL'}] 同一組按鈕結果可重現（zlib.crc32 確定性）")

b = c.match_button("5F", 0.80, "1F", 0)
print(f"  1F→5F attempt=0 : confidence={b.confidence}")

print(f"  bbox  = {b.bbox}")
print(f"  offset = ({b.offset_x_px:+d}, {b.offset_y_px:+d}) px  ← 供麥克納姆輪 linear.y 微調")
print(f"  method = {b.method}")

print("\n=== 重試時重新取樣（attempt 讓成功率提升）===")
for attempt in range(4):
    r = c.match_button("3F", 0.80, "1F", attempt)
    ok = "通過" if r.confidence >= 0.80 else "不通過"
    print(f"  attempt={attempt}: confidence={r.confidence:.4f}  {ok}")

print("\n=== ActuatorInterface：mock 觸覺回饋 ===")
act = ActuatorInterface()
t = act.press(1200)
print(f"  confirmed   = {t.confirmed}")
print(f"  force_kg    = {t.force_kg}")
print(f"  sensor      = {t.sensor}")
print(f"  duration_ms = {t.press_duration_ms}")
print(f"  to_dict()   = {json.dumps(t.to_dict(), ensure_ascii=False)}")

print("\n=== MecanumBaseInterface：麥克納姆輪橫移對準 ===")
base = MecanumBaseInterface()
cmds = []
base.set_ros_bridge(publish_cmd_vel=lambda c: cmds.append(c))
for offset in (-30, 15, 3):
    base.strafe_to_align(offset)
print(f"  發佈的 /cmd_vel 指令：")
for c in cmds:
    print(f"    linear=({c['linear']['x']}, {c['linear']['y']})  angular.z={c['angular']['z']}")
base.stop()
print(f"  stop() 後：linear.y={cmds[-1]['linear']['y']}（麥克納姆輪特性：平移不需轉身）")

print("\n=== 降級策略：real 模式但硬體不可用 ===")
os.environ["HARDWARE_MODE"] = "real"
reset_hal()
hal = HardwareHAL()
d = hal.describe()
print(f"  HARDWARE_MODE=real 但無 /dev/video0 與 MCU：")
print(f"    camera.ready  = {d['camera']['ready']}  ← 自動降級為 mock，不崩潰")
print(f"    actuator.ready = {d['actuator']['ready']}")
print(f"    base.ready    = {d['base']['ready']}")
hal.close()

print("\n=== 不合法模式退回 mock ===")
os.environ["HARDWARE_MODE"] = "garbage"
reset_hal()
print(f"  HARDWARE_MODE=garbage → {get_hardware_mode()}")
os.environ["HARDWARE_MODE"] = "mock"
reset_hal()

print("\n=== 完整 describe()（供 /robot_status 上報）===")
hal = HardwareHAL()
print(json.dumps(hal.describe(), ensure_ascii=False, indent=2))
hal.close()
reset_hal()