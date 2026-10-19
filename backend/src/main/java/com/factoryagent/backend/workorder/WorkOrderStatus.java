package com.factoryagent.backend.workorder;

/**
 * 작업자 처리 단계: 작성됨 → 작업자 확인 → 조치 완료(결과 입력).
 * 한 알람에 경고·위험 지시서가 따로 생기므로, 하나가 완료되면 나머지는 SUPERSEDED 로 함께 닫는다.
 */
public enum WorkOrderStatus {
    OPEN,
    ACKNOWLEDGED,
    COMPLETED,
    SUPERSEDED;

    public boolean isClosed() {
        return this == COMPLETED || this == SUPERSEDED;
    }
}
