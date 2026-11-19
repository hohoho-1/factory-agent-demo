-- 품질 홀드의 판정과 ERP 연계.
-- 품질팀이 홀드를 승인(APPROVED)하면 MES 가 ERP 에 알리고(hold_reported_at), 검사 후 판정한다.
--   disposition: PASS(합격 → 보류 해제, 출하 가능) / FAIL(불합격 → 폐기, ERP 가 재생산 오더를 계획)
--   disposition_reported_at: 판정을 ERP 에 알린 시각. 비어 있으면 다시 보낸다
ALTER TABLE quality_assessment ADD COLUMN disposition varchar(8);
ALTER TABLE quality_assessment ADD COLUMN disposition_by varchar(64);
ALTER TABLE quality_assessment ADD COLUMN disposition_at timestamp(6) with time zone;
ALTER TABLE quality_assessment ADD COLUMN disposition_note varchar(500);
ALTER TABLE quality_assessment ADD COLUMN hold_reported_at timestamp(6) with time zone;
ALTER TABLE quality_assessment ADD COLUMN disposition_reported_at timestamp(6) with time zone;
ALTER TABLE quality_assessment ADD CONSTRAINT quality_assessment_disposition_check
    CHECK (disposition IS NULL OR disposition IN ('PASS', 'FAIL'));
