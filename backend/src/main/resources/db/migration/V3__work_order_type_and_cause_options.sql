-- 1) 설비 유형: 같은 유형의 다른 설비(TANK-01 ↔ TANK-02) 조치 이력도 찾기 위해. 기존 행은 알람에서 채운다.
-- 2) 원인 선택지: 에이전트가 근거 매뉴얼의 '가능 원인'에서 뽑아 넣는다. 작업자는 고르거나 직접 입력한다.

ALTER TABLE work_order ADD COLUMN equipment_type varchar(32);
UPDATE work_order w SET equipment_type = a.equipment_type FROM alarm a WHERE a.id = w.alarm_id;
UPDATE work_order SET equipment_type = 'UNKNOWN' WHERE equipment_type IS NULL;
ALTER TABLE work_order ALTER COLUMN equipment_type SET NOT NULL;

ALTER TABLE work_order ADD COLUMN cause_options jsonb;

CREATE INDEX idx_work_order_type_metric_status ON work_order (equipment_type, metric, status);
