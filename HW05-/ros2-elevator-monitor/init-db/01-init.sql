-- =====================================================================
-- 01-init.sql
-- ROS 2 跨樓層巡檢機器人監控後台系統 - PostgreSQL 15 資料庫初始化
-- 掛載路徑： /docker-entrypoint-initdb.d/01-init.sql
-- 內容：樓層資訊資料表、按鈕座標特徵表、巡檢紀錄日誌表 + 預設資料
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 0. 擴充功能
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()

-- ---------------------------------------------------------------------
-- 1. 樓層資訊資料表 (Floor Meta)
--    儲存每層樓的地圖名稱、地圖路徑、電梯按鈕目標、停靠點位姿
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS floors (
    id                  SERIAL         PRIMARY KEY,
    floor_code          VARCHAR(16)    NOT NULL UNIQUE,          -- 樓層代號，例如 '1F' / 'B1'
    floor_index         SMALLINT       NOT NULL,                 -- 樓層高度序號（B1=-1、1F=1），用於排序與高度判斷
    name                VARCHAR(64)    NOT NULL,                 -- 顯示名稱
    map_name            VARCHAR(128)   NOT NULL,                 -- ROS 2 map server 的地圖名稱
    map_path            VARCHAR(255)   NOT NULL,                 -- 地圖檔 (.yaml) 路徑
    map_resolution      REAL           NOT NULL DEFAULT 0.05,    -- 地圖解析度 (m/px)
    has_elevator        BOOLEAN        NOT NULL DEFAULT TRUE,    -- 此樓層是否設有電梯
    elevator_id         VARCHAR(32)    NOT NULL DEFAULT 'E1',    -- 電梯編號
    elevator_button_target VARCHAR(16),                          -- 呼叫按鈕目標樓層 (跨樓層巡檢必填)
    dock_pose           JSONB,                                   -- 機器人停靠點 {"x":..,"y":..,"yaw":..}
    waiting_pose        JSONB,                                   -- 電梯前等待點 {"x":..,"y":..,"yaw":..}
    nav_goal_pose       JSONB,                                   -- 巡檢點預設導航目標
    description         TEXT,                                    -- 樓層用途說明
    is_active           BOOLEAN        NOT NULL DEFAULT TRUE,    -- 是否啟用
    sort_order          SMALLINT       NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_floors_floor_index CHECK (floor_index BETWEEN -5 AND 99),
    CONSTRAINT ck_floors_pose_json   CHECK (
        (dock_pose    IS NULL OR jsonb_typeof(dock_pose)    = 'object') AND
        (waiting_pose IS NULL OR jsonb_typeof(waiting_pose) = 'object') AND
        (nav_goal_pose IS NULL OR jsonb_typeof(nav_goal_pose) = 'object')
    )
);

COMMENT ON TABLE  floors               IS '樓層資訊資料表';
COMMENT ON COLUMN floors.floor_code    IS '樓層代號，例如 1F / B1';
COMMENT ON COLUMN floors.floor_index   IS '樓層高度序號，地下樓為負數';
COMMENT ON COLUMN floors.map_name      IS 'ROS 2 map server 地圖名稱';
COMMENT ON COLUMN floors.map_path      IS '地圖 yaml 檔路徑';
COMMENT ON COLUMN floors.dock_pose     IS '機器人停靠點位姿 JSONB';
COMMENT ON COLUMN floors.waiting_pose  IS '電梯前等待點位姿 JSONB';

CREATE INDEX IF NOT EXISTS ix_floors_floor_index ON floors (floor_index);
CREATE INDEX IF NOT EXISTS ix_floors_active      ON floors (is_active, floor_index);

-- updated_at 自動更新觸發器
CREATE OR REPLACE FUNCTION trg_set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tg_floors_updated_at ON floors;
CREATE TRIGGER tg_floors_updated_at
    BEFORE UPDATE ON floors
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- ---------------------------------------------------------------------
-- 2. 電梯按鈕座標特徵表 (Button Features)
--    供 button_recognizer.py 做模板比對 (Template Matching) 與按壓驗證
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS floor_button_features (
    id                  SERIAL         PRIMARY KEY,
    floor_code          VARCHAR(16)    NOT NULL,
    elevator_id         VARCHAR(32)    NOT NULL DEFAULT 'E1',
    button_label        VARCHAR(16)    NOT NULL,                 -- 按鈕面板上的文字，例如 '5F'
    target_floor_code   VARCHAR(16),                             -- 按下後應到達的樓層
    label_x             INTEGER        NOT NULL DEFAULT 0,      -- 按鈕外框左上角 (px)
    label_y             INTEGER        NOT NULL DEFAULT 0,
    label_width         INTEGER        NOT NULL DEFAULT 60,
    label_height        INTEGER        NOT NULL DEFAULT 60,
    center_x            REAL           NOT NULL DEFAULT 0.5,    -- 正規化中心點 (0~1)
    center_y            REAL           NOT NULL DEFAULT 0.5,
    norm_width          REAL           NOT NULL DEFAULT 0.08,    -- 正規化寬度 (0~1)
    norm_height         REAL           NOT NULL DEFAULT 0.08,    -- 正規化高度 (0~1)
    template_path       VARCHAR(255),                           -- 按鈕模板圖檔路徑
    confidence_threshold REAL          NOT NULL DEFAULT 0.75,   -- 視覺確認信賴門檻
    press_duration_ms   INTEGER        NOT NULL DEFAULT 1200,    -- 按壓持續時間 (毫秒)
    is_active           BOOLEAN        NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_button_floor      FOREIGN KEY (floor_code)
        REFERENCES floors (floor_code) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_button_target     FOREIGN KEY (target_floor_code)
        REFERENCES floors (floor_code) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT uq_button_unique     UNIQUE (floor_code, elevator_id, button_label),
    CONSTRAINT ck_button_bbox        CHECK (label_width > 0 AND label_height > 0),
    CONSTRAINT ck_button_norm        CHECK (
        center_x BETWEEN 0 AND 1 AND center_y BETWEEN 0 AND 1 AND
        norm_width > 0 AND norm_width <= 1 AND norm_height > 0 AND norm_height <= 1
    ),
    CONSTRAINT ck_button_threshold   CHECK (confidence_threshold > 0 AND confidence_threshold <= 1)
);

COMMENT ON TABLE  floor_button_features                  IS '電梯按鈕座標特徵表';
COMMENT ON COLUMN floor_button_features.button_label     IS '按鈕面板文字標籤';
COMMENT ON COLUMN floor_button_features.target_floor_code IS '按下此按鈕後預期到達的樓層';
COMMENT ON COLUMN floor_button_features.template_path    IS '模板比對用圖檔 (.png)';

CREATE INDEX IF NOT EXISTS ix_button_floor        ON floor_button_features (floor_code, elevator_id);
CREATE INDEX IF NOT EXISTS ix_button_target_floor ON floor_button_features (target_floor_code);

DROP TRIGGER IF EXISTS tg_button_updated_at ON floor_button_features;
CREATE TRIGGER tg_button_updated_at
    BEFORE UPDATE ON floor_button_features
    FOR EACH ROW EXECUTE FUNCTION trg_set_updated_at();

-- ---------------------------------------------------------------------
-- 3. 巡檢紀錄日誌表 (Inspection Logs)
--    記錄 FSM 狀態轉移、電梯搭乘、按鈕確認、地圖切換…等所有關鍵事件
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inspection_logs (
    id                  BIGSERIAL      PRIMARY KEY,
    inspection_uuid     UUID           NOT NULL,                 -- 同一趟巡檢任務共用
    robot_name          VARCHAR(64)    NOT NULL DEFAULT 'amr_01',
    task_name           VARCHAR(128),                            -- 巡檢任務名稱
    event_type          VARCHAR(32)    NOT NULL,                 -- 事件類型
    status              VARCHAR(16)    NOT NULL DEFAULT 'running',
    log_level           VARCHAR(8)     NOT NULL DEFAULT 'INFO',
    from_floor_code     VARCHAR(16),                            -- 出發樓層
    to_floor_code       VARCHAR(16),                            -- 目標樓層
    floor_code          VARCHAR(16),                            -- 事件發生時所在樓層
    message             TEXT,                                   -- 事件描述
    detail              JSONB          DEFAULT '{}'::jsonb,      -- 額外資訊 (比對分數、按壓結果…)
    duration_ms         INTEGER,                                -- 此步驟耗時 (毫秒)
    success             BOOLEAN,                                -- 此事件是否成功
    occurred_at         TIMESTAMPTZ    NOT NULL DEFAULT NOW(),   -- 事件實際發生時間 (機器人時戳)
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT NOW(),   -- 寫入資料庫時間
    CONSTRAINT ck_logs_event_type CHECK (event_type IN (
        'task_start', 'task_finish', 'fsm_transition', 'nav_result',
        'elevator_call', 'elevator_enter', 'elevator_exit',
        'button_detect', 'button_press', 'map_switch', 'info', 'error'
    )),
    CONSTRAINT ck_logs_status  CHECK (status IN ('running', 'success', 'failed', 'cancelled', 'warning')),
    CONSTRAINT ck_logs_level   CHECK (log_level IN ('DEBUG', 'INFO', 'WARN', 'ERROR')),
    CONSTRAINT ck_logs_from    FOREIGN KEY (from_floor_code)
        REFERENCES floors (floor_code) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT ck_logs_to      FOREIGN KEY (to_floor_code)
        REFERENCES floors (floor_code) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT ck_logs_floor   FOREIGN KEY (floor_code)
        REFERENCES floors (floor_code) ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT ck_logs_detail  CHECK (detail IS NULL OR jsonb_typeof(detail) = 'object'),
    CONSTRAINT ck_logs_duration CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

COMMENT ON TABLE  inspection_logs                IS '巡檢紀錄日誌表';
COMMENT ON COLUMN inspection_logs.inspection_uuid IS '巡檢任務唯一識別碼 (同一趟共用)';
COMMENT ON COLUMN inspection_logs.event_type      IS '事件類型';
COMMENT ON COLUMN inspection_logs.detail          IS '事件額外資訊 JSONB';
COMMENT ON COLUMN inspection_logs.occurred_at     IS '事件發生時間 (來自機器人)';

CREATE INDEX IF NOT EXISTS ix_logs_inspection ON inspection_logs (inspection_uuid);
CREATE INDEX IF NOT EXISTS ix_logs_occurred   ON inspection_logs (occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_logs_event      ON inspection_logs (event_type);
CREATE INDEX IF NOT EXISTS ix_logs_status     ON inspection_logs (status);
CREATE INDEX IF NOT EXISTS ix_logs_floor      ON inspection_logs (floor_code);

-- ---------------------------------------------------------------------
-- 4. 巡檢統計檢視 (供 /api/v1/inspections/summary 使用)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_inspection_summary AS
SELECT
    inspection_uuid,
    MIN(robot_name)        AS robot_name,
    MAX(task_name)         AS task_name,
    MIN(occurred_at)       AS started_at,
    MAX(occurred_at)       AS finished_at,
    COUNT(*)               AS event_count,
    COUNT(*) FILTER (WHERE status = 'error' OR log_level = 'ERROR') AS error_count,
    BOOL_OR(status = 'failed')            AS has_failed,
    BOOL_AND(status = 'success')          AS all_success,
    (ARRAY_AGG(to_floor_code  ORDER BY occurred_at DESC))[1] AS final_floor_code
FROM inspection_logs
GROUP BY inspection_uuid;

COMMENT ON VIEW v_inspection_summary IS '每趟巡檢任務的彙總檢視';

-- ---------------------------------------------------------------------
-- 5. 預設資料：樓層資訊
-- ---------------------------------------------------------------------
INSERT INTO floors
    (floor_code, floor_index, name, map_name, map_path, map_resolution,
     has_elevator, elevator_id, elevator_button_target,
     dock_pose, waiting_pose, nav_goal_pose, description, sort_order)
VALUES
    ('B2', -2, '地下二樓 停車場',  'building_b2', '/maps/building_b2.yaml',  0.05, TRUE, 'E1', '1F',
     '{"x": 1.20, "y": -0.80, "yaw": 0.00}',
     '{"x": 0.60, "y":  1.60, "yaw": 1.57}',
     '{"x": 8.50, "y": 4.20, "yaw": 3.14}',
     '停車場巡檢區，含 120 個車位', -2),

    ('B1', -1, '地下一樓 機房區',  'building_b1', '/maps/building_b1.yaml',  0.05, TRUE, 'E1', '1F',
     '{"x": 1.05, "y": -0.95, "yaw": 0.10}',
     '{"x": 0.55, "y":  1.50, "yaw": 1.57}',
     '{"x": 7.90, "y": 3.10, "yaw": 3.14}',
     '機房與配電室溫溼度監控', -1),

    ('1F',   1, '一樓 大廳與服務台', 'building_1f', '/maps/building_1f.yaml',  0.05, TRUE, 'E1', '2F',
     '{"x": 0.90, "y": -1.10, "yaw": -0.15}',
     '{"x": 0.50, "y":  1.40, "yaw": 1.57}',
     '{"x": 6.40, "y": 2.60, "yaw": 3.14}',
     '大廳、服務台與訪客動線', 1),

    ('2F',   2, '二樓 會議區',      'building_2f', '/maps/building_2f.yaml',  0.05, TRUE, 'E1', '3F',
     '{"x": 1.15, "y": -0.85, "yaw": 0.05}',
     '{"x": 0.58, "y":  1.52, "yaw": 1.57}',
     '{"x": 9.10, "y": 5.30, "yaw": 3.14}',
     '會議室與開放式辦公區', 2),

    ('3F',   3, '三樓 實驗室',      'building_3f', '/maps/building_3f.yaml',  0.05, TRUE, 'E1', '4F',
     '{"x": 0.85, "y": -1.05, "yaw": 0.08}',
     '{"x": 0.48, "y": 1.45, "yaw": 1.57}',
     '{"x": 7.20, "y": 6.80, "yaw": 3.14}',
     '機器人實驗室與感測器測試區', 3),

    -- 電梯 E1 服務 B2 ~ 5F 全棟，故所有樓層 has_elevator = TRUE；
    -- 最頂樓 5F 沒有更高的按鈕可按，因此 elevator_button_target = NULL。
    ('4F',   4, '四樓 主管辦公區',  'building_4f', '/maps/building_4f.yaml',  0.05, TRUE, 'E1', '5F',
     '{"x": 1.00, "y": -1.00, "yaw": 0.00}',
     '{"x": 0.52, "y": 1.48, "yaw": 1.57}',
     '{"x": 5.80, "y": 3.90, "yaw": 3.14}',
     '主管辦公室與茶水間', 4),

    ('5F',   5, '五樓 天台與機房',  'building_5f', '/maps/building_5f.yaml',  0.05, TRUE, 'E1', NULL,
     '{"x": 1.10, "y": -0.90, "yaw": 0.00}',
     '{"x": 0.55, "y": 1.50, "yaw": 1.57}',
     '{"x": 4.60, "y": 7.20, "yaw": 3.14}',
     '屋頂機房與太陽能板巡檢點', 5)
ON CONFLICT (floor_code) DO UPDATE SET
    floor_index             = EXCLUDED.floor_index,
    name                    = EXCLUDED.name,
    map_name                = EXCLUDED.map_name,
    map_path                = EXCLUDED.map_path,
    map_resolution          = EXCLUDED.map_resolution,
    has_elevator            = EXCLUDED.has_elevator,
    elevator_id             = EXCLUDED.elevator_id,
    elevator_button_target  = EXCLUDED.elevator_button_target,
    dock_pose               = EXCLUDED.dock_pose,
    waiting_pose            = EXCLUDED.waiting_pose,
    nav_goal_pose           = EXCLUDED.nav_goal_pose,
    description             = EXCLUDED.description,
    sort_order              = EXCLUDED.sort_order;

-- ---------------------------------------------------------------------
-- 6. 預設資料：電梯按鈕座標特徵
--    E1 電梯廳面板為 1920x1080 影像座標系，採雙排配置：
--      第一排 4 顆 (y=420)，第二排 3 顆 (y=490)，按鈕 64x64、間距 70px
--    這裡以 INSERT ... SELECT 為每個樓層自動產生「全部樓層」的按鈕特徵，
--    讓 FSM 在任意樓層都能查到目標樓層按鈕。
-- ---------------------------------------------------------------------
WITH targets AS (
    SELECT
        f.floor_code AS button_label,
        ROW_NUMBER() OVER (ORDER BY f.floor_index) AS seq,   -- 按鈕在面板上的順序
        COUNT(*)     OVER ()                        AS total   -- 面板按鈕總數
    FROM floors f
)
INSERT INTO floor_button_features
    (floor_code, elevator_id, button_label, target_floor_code,
     label_x, label_y, label_width, label_height,
     center_x, center_y, norm_width, norm_height,
     template_path, confidence_threshold, press_duration_ms)
SELECT
    f.floor_code,        -- 按鈕所在樓層（每層都有完整面板）
    'E1',
    t.button_label,
    t.button_label,
    760 + (t.seq - 1) * 70,                                   -- label_x
    CASE WHEN t.seq <= 4 THEN 420 ELSE 490 END,               -- label_y
    64,                                                        -- label_width
    64,                                                        -- label_height
    ROUND(((760 + (t.seq - 1) * 70) + 32)::numeric / 1920, 4),  -- center_x (正規化)
    ROUND(((CASE WHEN t.seq <= 4 THEN 420 ELSE 490 END) + 32)::numeric / 1080, 4), -- center_y
    ROUND(64::numeric / 1920, 4),                              -- norm_width
    ROUND(64::numeric / 1080, 4),                              -- norm_height
    '/maps/buttons/E1_' || t.button_label || '.png',
    0.80,
    1200
FROM floors f
CROSS JOIN targets t
ON CONFLICT (floor_code, elevator_id, button_label) DO UPDATE SET
    target_floor_code   = EXCLUDED.target_floor_code,
    label_x             = EXCLUDED.label_x,
    label_y             = EXCLUDED.label_y,
    label_width         = EXCLUDED.label_width,
    label_height        = EXCLUDED.label_height,
    center_x            = EXCLUDED.center_x,
    center_y            = EXCLUDED.center_y,
    norm_width          = EXCLUDED.norm_width,
    norm_height         = EXCLUDED.norm_height,
    template_path       = EXCLUDED.template_path,
    confidence_threshold = EXCLUDED.confidence_threshold,
    press_duration_ms   = EXCLUDED.press_duration_ms,
    is_active           = TRUE;

-- ---------------------------------------------------------------------
-- 7. 預設資料：一筆歷史巡檢紀錄，方便前端一開始就有資料顯示
-- ---------------------------------------------------------------------
INSERT INTO inspection_logs
    (inspection_uuid, robot_name, task_name, event_type, status, log_level,
     from_floor_code, to_floor_code, floor_code, message, detail,
     duration_ms, success, occurred_at)
VALUES
    ('11111111-1111-4111-8111-000000000001', 'amr_01', '每日例行巡檢 (1F→5F)',
     'task_start', 'running', 'INFO', '1F', '5F', '1F',
     '開始執行跨樓層巡檢任務',
     '{"waypoints": ["1F", "2F", "3F", "4F", "5F"], "operator": "admin"}',
     NULL, NULL, NOW() - INTERVAL '15 minutes'),

    ('11111111-1111-4111-8111-000000000001', 'amr_01', '每日例行巡檢 (1F→5F)',
     'button_press', 'success', 'INFO', '1F', '2F', '1F',
     '視覺確認 2F 按鈕成功 (相似度 0.93)，已按壓 1200ms',
     '{"vision_confidence": 0.93, "tactile_confirmed": true, "template": "/maps/buttons/E1_2F.png"}',
     1200, TRUE, NOW() - INTERVAL '14 minutes'),

    ('11111111-1111-4111-8111-000000000001', 'amr_01', '每日例行巡檢 (1F→5F)',
     'map_switch', 'success', 'INFO', '1F', '2F', '2F',
     '地圖切換完成：building_1f → building_2f',
     '{"from_map": "building_1f", "to_map": "building_2f"}',
     2400, TRUE, NOW() - INTERVAL '13 minutes'),

    ('11111111-1111-4111-8111-000000000001', 'amr_01', '每日例行巡檢 (1F→5F)',
     'nav_result', 'success', 'INFO', '1F', '2F', '2F',
     '抵達 2F 巡檢點',
     '{"goal": {"x": 9.1, "y": 5.3, "yaw": 3.14}}',
     18700, TRUE, NOW() - INTERVAL '12 minutes')
ON CONFLICT DO NOTHING;

COMMIT;

-- =====================================================================
-- 初始化完成
-- =====================================================================
\echo '======================================================'
\echo ' elevator_monitor 資料庫初始化完成'
\echo '  - floors                 : 樓層資訊資料表'
\echo '  - floor_button_features  : 電梯按鈕座標特徵表'
\echo '  - inspection_logs        : 巡檢紀錄日誌表'
\echo '  - v_inspection_summary   : 巡檢統計檢視'
\echo '======================================================'
