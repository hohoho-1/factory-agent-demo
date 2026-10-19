package com.factoryagent.backend.workorder;

/** 작업자 처리 단계: 작성됨 → 작업자 확인 → 조치 완료(결과 입력). */
public enum WorkOrderStatus {
    OPEN,
    ACKNOWLEDGED,
    COMPLETED
}
