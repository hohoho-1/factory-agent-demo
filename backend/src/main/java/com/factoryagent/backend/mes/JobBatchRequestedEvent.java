package com.factoryagent.backend.mes;

/** 작업자가 배치를 시작했다. 커밋 후 PLC 배치 요청 명령을 MQTT 로 내려보낸다. */
public record JobBatchRequestedEvent(Long requestId, String equipmentId, String batchId, String recipe, String worker) {
}
