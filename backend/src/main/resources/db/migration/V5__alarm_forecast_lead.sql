-- 추세 기반 예측 경보가 이 알람을 몇 초 먼저 예측했는지. 예측 없이 발생한 알람은 null.
ALTER TABLE alarm ADD COLUMN forecast_lead_seconds bigint;
