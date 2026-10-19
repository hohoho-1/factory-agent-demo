package com.factoryagent.backend.workorder;

/** 작업자 확인·조치 완료로 지시서 상태가 바뀜. */
public record WorkOrderUpdatedEvent(WorkOrder workOrder) {
}
