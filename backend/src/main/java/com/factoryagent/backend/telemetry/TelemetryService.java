package com.factoryagent.backend.telemetry;

import com.factoryagent.backend.alarm.AlarmService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;
import java.util.Map;

@Service
public class TelemetryService {

    private static final Logger log = LoggerFactory.getLogger(TelemetryService.class);

    private final ObjectMapper objectMapper;
    private final SensorReadingRepository repository;
    private final AlarmService alarmService;

    public TelemetryService(ObjectMapper objectMapper, SensorReadingRepository repository,
                            AlarmService alarmService) {
        this.objectMapper = objectMapper;
        this.repository = repository;
        this.alarmService = alarmService;
    }

    /** MQTT payload(JSON) 1건을 지표별 행으로 펼쳐 저장하고 이상 여부를 판정한다. 형식이 잘못된 메시지는 버린다. */
    @Transactional
    public void ingest(String topic, String payload) {
        TelemetryMessage msg;
        try {
            msg = objectMapper.readValue(payload, TelemetryMessage.class);
        } catch (JsonProcessingException e) {
            log.warn("invalid telemetry on {}: {}", topic, e.getOriginalMessage());
            return;
        }
        if (msg.equipmentId() == null || msg.ts() == null || msg.metrics() == null) {
            log.warn("incomplete telemetry on {}: {}", topic, payload);
            return;
        }

        Instant measuredAt = msg.ts().toInstant();
        Instant receivedAt = Instant.now();
        Map<String, String> units = msg.units() == null ? Map.of() : msg.units();

        List<SensorReading> rows = msg.metrics().entrySet().stream()
                .filter(e -> e.getValue() != null)
                .map(e -> new SensorReading(msg.equipmentId(), msg.type(), e.getKey(), e.getValue(),
                        units.get(e.getKey()), measuredAt, receivedAt))
                .toList();
        repository.saveAll(rows);
        rows.forEach(alarmService::evaluate);
        log.debug("saved {} readings from {}", rows.size(), msg.equipmentId());
    }

    @Transactional(readOnly = true)
    public List<SensorReading> latest() {
        return repository.findLatestPerMetric();
    }
}
