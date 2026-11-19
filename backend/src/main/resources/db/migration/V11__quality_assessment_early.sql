-- 급한 판단 먼저: 품질 규칙 판정은 알람 직후 지시서보다 먼저 저장한다.
-- 지시서는 나중에 연결되므로 work_order_id 를 비워 둘 수 있게 한다.
ALTER TABLE quality_assessment ALTER COLUMN work_order_id DROP NOT NULL;
CREATE INDEX idx_quality_assessment_alarm ON quality_assessment (alarm_id);
