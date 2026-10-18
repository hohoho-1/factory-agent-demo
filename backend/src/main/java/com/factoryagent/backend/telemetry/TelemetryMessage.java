package com.factoryagent.backend.telemetry;

import java.time.OffsetDateTime;
import java.util.Map;

/** python/sensors/virtual_sensors.py 가 발행하는 MQTT payload. */
public record TelemetryMessage(
        String equipmentId,
        String type,
        OffsetDateTime ts,
        Map<String, Double> metrics,
        Map<String, String> units
) {
}
