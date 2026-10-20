package com.factoryagent.backend.telemetry;

import java.time.OffsetDateTime;
import java.util.Map;

/**
 * 가상 센서·엣지 게이트웨이가 발행하는 MQTT payload.
 *
 * @param state 문자열 상태 태그 (가상 PLC 의 배치 단계 batchPhase · batchId · recipe). 가상 센서 모드에는 없다
 */
public record TelemetryMessage(
        String equipmentId,
        String type,
        OffsetDateTime ts,
        Map<String, Double> metrics,
        Map<String, String> units,
        Map<String, String> state
) {
}
