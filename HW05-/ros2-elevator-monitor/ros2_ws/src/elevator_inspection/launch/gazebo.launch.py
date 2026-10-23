#!/usr/bin/env python3
"""Gazebo Server 啟動檔（支援 Headless）。

沿用 ROS 2 標準的 `gazebo.launch.py` 慣例，
讓 `gazebo_elevator.launch.py` 可透過 `<include>` 引入。

Headless 環境（Docker / 無 X server）用法::

    ros2 launch elevator_inspection gazebo_elevator.launch.py gui:=false

需要已安裝 ``ros-humble-gazebo-ros-pkgs``。
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, LogInfo
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory("elevator_inspection")

    world = LaunchConfiguration("world")
    gui = LaunchConfiguration("gui")
    paused = LaunchConfiguration("paused")

    # Server：Headless（容器 / CI 環境）
    # -e 指定模擬時間更新率，確保感測器與控制器時序穩定
    server = ExecuteProcess(
        cmd=[
            "gzserver", "--verbose",
            "-e", "physics real_time_update_rate=1000",
            world,
            "-s", "libgazebo_ros_factory.so",
            "-s", "libgazebo_ros_state_publisher.so",
            "-s", "libgazebo_ros_api_plugin.so",
        ],
        output="screen",
        additional_env={
            "GAZEBO_MODEL_PATH": os.pathsep.join(
                filter(None, [os.path.join(pkg_share, "models"),
                              os.environ.get("GAZEBO_MODEL_PATH", "")])
            )
        },
        condition=UnlessCondition(gui),
    )

    # Client：GUI 預設關閉（Headless 優先）
    client = ExecuteProcess(
        cmd=["gzclient", "--verbose"],
        output="screen",
        condition=IfCondition(gui),
        additional_env={"DISPLAY": os.environ.get("DISPLAY", ":0")},
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            "world",
            default_value=os.path.join(pkg_share, "worlds", "campus_elevator.world"),
            description="Gazebo 世界檔路徑",
        ),
        DeclareLaunchArgument("gui", default_value="false",
                              description="是否啟動 Gazebo GUI"),
        DeclareLaunchArgument("paused", default_value="false",
                              description="啟動時是否暫停物理模擬"),
        LogInfo(msg=["Gazebo 啟動：world=", world, "  gui=", gui]),
        server,
        client,
    ])