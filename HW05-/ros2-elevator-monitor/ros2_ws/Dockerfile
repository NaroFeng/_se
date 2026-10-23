# =====================================================================
# ros2-bridge : Ubuntu 22.04 + ROS 2 Humble
# 職責：
#   1. rosbridge_server (WebSocket 9090) 傳遞即時姿態與狀態
#   2. 跨樓層巡檢狀態機 FSM (fsm_node.py)
#   3. 按鈕視覺比對 (button_recognizer.py)
#   4. 地圖動態切換 (Map Switching)
#   5. bridge_rest_node：提供內部 REST 控制埠 (8080) 給 web-backend 下指令
# =====================================================================
FROM ros:humble-ros-base

LABEL maintainer="SE-HW05" \
      description="ROS 2 Humble bridge + FSM for cross-floor elevator inspection"

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Taipei \
    ROS_DOMAIN_ID=42 \
    RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
    PYTHONUNBUFFERED=1 \
    APT_RETRIES=5

# apt 下載失敗時自動重試（-o Acquire::Retries），避免暫時性網路異常導致建置失敗
RUN printf '#!/bin/sh\nset -e\napt-get -o Acquire::Retries=%s update\napt-get -o Acquire::Retries=%s install -y --no-install-recommends "$@"\nrm -rf /var/lib/apt/lists/*\n' "$APT_RETRIES" "$APT_RETRIES" > /usr/local/bin/apt-retry-install \
    && chmod +x /usr/local/bin/apt-retry-install

# ---- ROS 2 相依套件 ----
RUN apt-retry-install \
        ros-humble-rosbridge-server \
        ros-humble-rosbridge-suite \
        ros-humble-nav2-bringup \
        ros-humble-nav2-map-server \
        ros-humble-tf2-ros \
        ros-humble-tf2-tools \
        ros-humble-diagnostic-updater \
        ros-humble-image-transport \
        ros-humble-cv-bridge \
        ros-humble-xacro \
        ros-humble-robot-state-publisher

# ---- Digital Twin（Gazebo 仿真，選配）----
# 設為 INSTALL_GAZEBO=false 時跳過，讓一般部署不必下載額外 ~500MB。
# 需要跑 Gazebo GUI 仿真時： docker compose build --build-arg INSTALL_GAZEBO=true
ARG INSTALL_GAZEBO=false
RUN if [ "${INSTALL_GAZEBO}" = "true" ]; then \
        apt-retry-install \
            ros-humble-gazebo-ros-pkgs \
            ros-humble-gazebo-plugins \
            gazebo11; \
    else \
        echo "略過 Gazebo（INSTALL_GAZEBO=${INSTALL_GAZEBO}），Headless 模式仍可用"; \
    fi

# ---- Python 3.10 相依套件 ----
RUN apt-retry-install \
        python3-pip \
        python3-numpy \
        python3-opencv \
        python3-yaml \
        python3-requests \
        python3-colcon-common-extensions \
        netcat-openbsd \
        curl

# ---- Python 相依套件說明 ----
# numpy / opencv / yaml / requests 皆由上一步 apt 安裝（見 ROS 2 Humble 相依套件）。
# 刻意不使用 pip 覆蓋：
#   Ubuntu 22.04 內建 pip 22.0.2，不支援 --break-system-packages 參數；
#   且 pip 安裝到 /usr/local/lib 會優先於 apt 的 /usr/lib，
#   會使 OpenCV 版本 (4.9) 蓋掉 ROS 2 Humble 搭配的版本 (4.5.4)，導致 cv_bridge 失效。
# 若 Step 3 需要 YOLO 等額外套件，請在此新增並確認相容性。

# ---- 建立 colcon 工作區 ----
RUN mkdir -p /ros2_ws/src /ros2_ws/install /ros2_ws/log
WORKDIR /ros2_ws

# ---- 複製 ROS 2 Python Package 原始碼 ----
COPY src /ros2_ws/src
COPY entrypoint.sh /ros2_ws/entrypoint.sh
RUN chmod +x /ros2_ws/entrypoint.sh

# ---- 預先建置工作區 ----
RUN . /opt/ros/humble/setup.sh && \
    colcon build --symlink-install --packages-select elevator_inspection && \
    rm -rf /ros2_ws/log/*

# ---- 以非 root 執行 ----
RUN useradd --create-home --shell /bin/bash rosuser && \
    chown -R rosuser:rosuser /ros2_ws
USER rosuser

EXPOSE 9090 8080

HEALTHCHECK --interval=20s --timeout=5s --start-period=40s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["/ros2_ws/entrypoint.sh"]