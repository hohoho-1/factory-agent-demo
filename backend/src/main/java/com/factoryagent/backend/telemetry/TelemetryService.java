package com.factoryagent.backend.telemetry;

import com.factoryagent.backend.alarm.AlarmService;
import com.factoryagent.backend.batch.BatchStateTracker;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;

@Service
public class TelemetryService {

    private static final Logger log = LoggerFactory.getLogger(TelemetryService.class);
    private static final int MAX_HISTORY_MINUTES = 60;

    private final ObjectMapper objectMapper;
    private final SensorReadingRepository repository;
    private final AlarmService alarmService;
    private final ApplicationEventPublisher events;
    private final BatchStateTracker batches;

    public TelemetryService(ObjectMapper objectMapper, SensorReadingRepository repository,
                            AlarmService alarmService, ApplicationEventPublisher events, BatchStateTracker batches) {
        this.objectMapper = objectMapper;
        this.repository = repository;
        this.alarmService = alarmService;
        this.events = events;
        this.batches = batches;
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
        // 배치 단계를 먼저 반영해야 알람 판정이 지금 단계의 기준을 쓴다
        batches.observe(msg.equipmentId(), msg.state(), measuredAt).ifPresent(e -> {
            alarmService.onPhaseChange(e);
            events.publishEvent(e);
        });
        rows.forEach(alarmService::evaluate);
        events.publishEvent(new ReadingsSavedEvent(rows));
        log.debug("saved {} readings from {}", rows.size(), msg.equipmentId());
    }

    @Transactional(readOnly = true)
    public List<SensorReading> latest() {
        return repository.findLatestPerMetric();
    }

    /** 최근 N분 측정값 (대시보드 차트 초기 로딩용, 최대 60분). */
    @Transactional(readOnly = true)
    public List<SensorReading> history(int minutes) {
        int clamped = Math.max(1, Math.min(minutes, MAX_HISTORY_MINUTES));
        return repository.findByMeasuredAtAfterOrderByMeasuredAtAsc(
                Instant.now().minus(Duration.ofMinutes(clamped)));
    }
}
