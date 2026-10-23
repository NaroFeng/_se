#!/usr/bin/env python3
"""Headless 閉環測試啟動檔（不需 Gazebo）。

只啟動 `elevator_sim_node`，配合 `fsm_node` + `button_recognizer`
即可在沒有 Gazebo GUI、甚至沒有 Gazebo 的情況下完成端到端閉環驗證。

優點：
  * 不依賴 Gazebo 與 GPU，CI 上也能跑
  * 啟動只需數秒，適合每次改程式後快速回歸
  * 電梯開關門由 `elevator_sim_node` 的狀態機決定，結果可重現

用法::

    ros2 launch elevator_inspection elevator_sim_headless.launch.py
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, LogInfo, TimerAction
from launch.substitutions import EnvironmentVariable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    hardware_mode = LaunchConfiguration("hardware_mode")
    robot_name = LaunchConfiguration("robot_name")

    return LaunchDescription([
        # ---------------- 參數 ----------------
        DeclareLaunchArgument(
            "hardware_mode",
            default_value="gazebo",
            description="HARDWARE_MODE：gazebo（Digital Twin，Headless 感測器）",
        ),
        DeclareLaunchArgument(
            "robot_name",
            default_value="amr-proto-01",
            description="機器人識別碼（中央大腦匯流用）",
        ),
        DeclareLaunchArgument(
            "use_fake_sensors",
            default_value="true",
            description="由 elevator_sim_node 產生偽 LiDAR / 相機",
        ),
        DeclareLaunchArgument(
            "start_floor",
            default_value="1F",
            description="模擬起始樓層",
        ),

        LogInfo(msg=[
            "================ Headless Digital Twin ================\n",
            "  HARDWARE_MODE = ", hardware_mode,
            "\n  ROBOT_NAME    = ", robot_name,
            "\n  無需 Gazebo：LiDAR / 相機由 elevator_sim_node 偽產生\n",
            "=======================================================",
        ]),

        # ---------------- 電梯模擬環境 ----------------
        Node(
            package="elevator_inspection",
            executable="elevator_sim_node",
            name="elevator_sim_node",
            output="screen",
            emulate_tty=True,
            parameters=[{
                "use_fake_sensors": LaunchConfiguration("use_fake_sensors"),
                "sim_start_floor": LaunchConfiguration("start_floor"),
            }],
            additional_env={
                "HARDWARE_MODE": hardware_mode,
                "ROBOT_NAME": robot_name,
                "USE_FAKE_SENSORS": LaunchConfiguration("use_fake_sensors"),
                "SIM_START_FLOOR": LaunchConfiguration("start_floor"),
                "PYTHONUNBUFFERED": "1",
            },
        ),

        # ---------------- 狀態機（延遲 1s 讓模擬節點先就緒）----------------
        TimerAction(
            period=1.0,
            actions=[
                Node(
                    package="elevator_inspection",
                    executable="fsm_node",
                    name="fsm_node",
                    output="screen",
                    emulate_tty=True,
                    additional_env={
                        "HARDWARE_MODE": hardware_mode,
                        "ROBOT_NAME": robot_name,
                        "DEFAULT_FLOOR": LaunchConfiguration("start_floor"),
                        "PYTHONUNBUFFERED": "1",
                    },
                ),
            ],
        ),

        # ---------------- 按鈕辨識 ----------------
        TimerAction(
            period=1.5,
            actions=[
                Node(
                    package="elevator_inspection",
                    executable="button_recognizer",
                    name="button_recognizer",
                    output="screen",
                    emulate_tty=True,
                    additional_env={
                        "HARDWARE_MODE": hardware_mode,
                        "PYTHONUNBUFFERED": "1",
                    },
                ),
            ],
        ),
    ])