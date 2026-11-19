package com.factoryagent.backend.mes;

/** 작업자가 세정을 시작했다. 커밋 후 PLC 세정 요청 명령(cleanRequest)을 MQTT 로 내려보낸다. */
public record CleanRequestedEvent(Long requestId, String equipmentId, String cipId, String worker) {
}
