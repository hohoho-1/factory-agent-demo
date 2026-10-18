package com.factoryagent.backend.telemetry;

import java.util.List;

/** MQTT 메시지 1건(설비 1대)에서 저장된 측정값들. */
public record ReadingsSavedEvent(List<SensorReading> readings) {
}
