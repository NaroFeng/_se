#!/usr/bin/env python3
"""Gazebo Digital Twin 完整啟動檔（機器人 + 世界 + 電梯模擬）。

啟動順序：
  1. `elevator_sim_node` — 電梯邏輯（門開關、樓層切換）
  2. Gazebo Server（Headless，載入 campus_elevator.world）
  3. Gazebo Client（GUI，可省略）
  4. robot_state_publisher（URTF）
  5. `fsm_node` + `button_recognizer`

用法::

    # 含 GUI
    ros2 launch elevator_inspection gazebo_elevator.launch.py gui:=true

    # Headless（Docker / 無顯示器環境，預設）
    ros2 launch elevator_inspection gazebo_elevator.launch.py
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory("elevator_inspection")
    world_path = os.path.join(pkg_share, "worlds", "campus_elevator.world")
    urdf_path = os.path.join(pkg_share, "urdf", "ikea_mecanum_bot.urdf.xacro")

    gui = LaunchConfiguration("gui")
    hardware_mode = LaunchConfiguration("hardware_mode")
    robot_name = LaunchConfiguration("robot_name")
    spawn_z = LaunchConfiguration("spawn_z")

    return LaunchDescription([
        DeclareLaunchArgument("gui", default_value="false",
                              description="是否啟動 Gazebo GUI"),
        DeclareLaunchArgument("hardware_mode", default_value="gazebo"),
        DeclareLaunchArgument("robot_name", default_value="amr-proto-01"),
        DeclareLaunchArgument("use_sim_time", default_value="true"),
        DeclareLaunchArgument("spawn_z", default_value="0.05",
                              description="機器人初始高度"),
        DeclareLaunchArgument("world", default_value=world_path),
        DeclareLaunchArgument("paused", default_value="false"),

        LogInfo(msg=["============ Gazebo Digital Twin ============",
                     "\n  world  = ", world_path,
                     "\n  GUI    = ", gui,
                     "\n  模式   = ", hardware_mode,
                     "\n=========================================="]),

        # ---------------- 1. 電梯邏輯（需先啟動，門板才有人驅動）----------------
        Node(
            package="elevator_inspection",
            executable="elevator_sim_node",
            name="elevator_sim_node",
            output="screen",
            emulate_tty=True,
            parameters=[{
                "use_fake_sensors": True,      # Gazebo 有真實 LiDAR，故關閉偽感測器
                "drive_gazebo_doors": True,    # 由模擬節點驅動 Gazebo 門板
            }],
            additional_env={
                "HARDWARE_MODE": hardware_mode,
                "ROBOT_NAME": robot_name,
                "USE_FAKE_SENSORS": "false",
                "DRIVE_GAZEBO_DOORS": "true",
                "PYTHONUNBUFFERED": "1",
            },
        ),

        # ---------------- 2. Gazebo Server（Headless）----------------
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(pkg_share, "launch", "gazebo.launch.py")
            ),
            launch_arguments={
                "world": LaunchConfiguration("world"),
                "gui": gui,
                "paused": LaunchConfiguration("paused"),
                "use_sim_time": LaunchConfiguration("use_sim_time"),
                "xacro": urdf_path,
            }.items(),
        ),

        # ---------------- 3. 機器人狀態發佈 ----------------
        TimerAction(
            period=2.0,
            actions=[
                Node(
                    package="robot_state_publisher",
                    executable="robot_state_publisher",
                    name="robot_state_publisher",
                    output="screen",
                    parameters=[{
                        "robot_description": Command(["xacro ", urdf_path]),
                        "use_sim_time": LaunchConfiguration("use_sim_time"),
                    }],
                ),
            ],
        ),

        # ---------------- 4. 將機器人投放到 Gazebo ----------------
        TimerAction(
            period=3.0,
            actions=[
                Node(
                    package="gazebo_ros",
                    executable="spawn_entity.py",
                    name="spawn_ikea_bot",
                    output="screen",
                    arguments=[
                        "-entity", "ikea_mecanum_bot",
                        "-topic", "/robot_description",
                        "-x", "-0.45",
                        "-y", "0.40",
                        "-z", spawn_z,
                        "-Y", "-1.5708",       # 面向電梯（+Y）
                    ],
                ),
            ],
        ),

        # ---------------- 5. 核心控制節點 ----------------
        TimerAction(
            period=5.0,
            actions=[
                Node(
                    package="elevator_inspection",
                    executable="fsm_node",
                    name="fsm_node",
                    output="screen",
                    emulate_tty=True,
                    parameters=[{"use_sim_time": LaunchConfiguration("use_sim_time")}],
                    additional_env={
                        "HARDWARE_MODE": hardware_mode,
                        "ROBOT_NAME": robot_name,
                        "PYTHONUNBUFFERED": "1",
                    },
                ),
                Node(
                    package="elevator_inspection",
                    executable="button_recognizer",
                    name="button_recognizer",
                    output="screen",
                    emulate_tty=True,
                    parameters=[{"use_sim_time": LaunchConfiguration("use_sim_time")}],
                    additional_env={
                        "HARDWARE_MODE": hardware_mode,
                        "PYTHONUNBUFFERED": "1",
                    },
                ),
            ],
        ),
    ])