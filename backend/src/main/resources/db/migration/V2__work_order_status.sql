-- 지시서 상태 정리
-- 1) 피드백 기능 이전에 만든 지시서(status null)를 OPEN 으로 채우고 NOT NULL 로 바꾼다.
-- 2) SUPERSEDED 추가: 같은 알람에서 다른 지시서가 조치 완료되면 나머지는 함께 닫힌다.
-- 3) 과거 조치 이력·통계 조회용 인덱스.

UPDATE work_order SET status = 'OPEN' WHERE status IS NULL;
ALTER TABLE work_order ALTER COLUMN status SET NOT NULL;

ALTER TABLE work_order DROP CONSTRAINT work_order_status_check;
ALTER TABLE work_order ADD CONSTRAINT work_order_status_check
    CHECK (status IN ('OPEN', 'ACKNOWLEDGED', 'COMPLETED', 'SUPERSEDED'));
ALTER TABLE work_order ADD COLUMN superseded_by bigint;

CREATE INDEX idx_work_order_eq_metric_status ON work_order (equipment_id, metric, status);
