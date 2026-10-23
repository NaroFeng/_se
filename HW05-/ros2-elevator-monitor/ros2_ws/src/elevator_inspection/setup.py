import os
from glob import glob

from setuptools import find_packages, setup

package_name = "elevator_inspection"


def _share_files(pattern: str) -> list:
    """收集 share 目錄下的資源檔（launch / urdf / worlds / models）。"""
    return [f for f in glob(os.path.join("share", package_name, pattern), recursive=True)]


setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        # Launch 啟動檔
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        # URDF / xacro 機器人模型
        ("share/" + package_name + "/urdf", glob("urdf/*.xacro") + glob("urdf/*.urdf")),
        # Gazebo 世界檔
        ("share/" + package_name + "/worlds", glob("worlds/*.world")),
        # Gazebo 自訂模型（若有的話）
        ("share/" + package_name + "/models", glob("models/*")),
        # 設定檔（按鈕模板路徑等）
        ("share/" + package_name + "/config", glob("config/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="SE-HW05",
    maintainer_email="se-hw05@example.com",
    description="ROS 2 跨樓層巡檢機器人監控後台系統 - 核心控制節點與 Digital Twin 仿真",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "fsm_node = elevator_inspection.fsm_node:main",
            "button_recognizer = elevator_inspection.button_recognizer:main",
            "bridge_rest_node = elevator_inspection.bridge_rest_node:main",
            # Digital Twin：電梯廳模擬環境（Headless / Gazebo 皆可）
            "elevator_sim_node = elevator_inspection.elevator_sim_node:main",
        ],
    },
)