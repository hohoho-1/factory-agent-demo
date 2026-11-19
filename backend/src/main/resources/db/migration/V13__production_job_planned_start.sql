-- 생산 지시의 계획 시작일 (ERP 생산 계획에서 온다). MES 는 이 순서로 지시를 보여 주고,
-- 앞 순서 지시를 두고 다른 지시의 배치를 시작하면 작업자 확인을 받고 '순서 변경'으로 기록한다.
ALTER TABLE production_job ADD COLUMN planned_start date;
ALTER TABLE production_job_batch ADD COLUMN out_of_order boolean NOT NULL DEFAULT false;
