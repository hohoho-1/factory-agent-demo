package com.factoryagent.backend.alarm;

import com.factoryagent.backend.batch.BatchPhaseEvent;
import com.factoryagent.backend.batch.BatchState;
import com.factoryagent.backend.batch.BatchStateTracker;
import com.factoryagent.backend.forecast.Forecast;
import com.factoryagent.backend.forecast.TrendForecaster;
import com.factoryagent.backend.telemetry.SensorReading;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 측정값을 임계값 규칙과 비교해 알람을 발생 · 상승 · 해제하고, 상태 변화를 AlarmEvent 로 알린다.
 * 기준을 넘기 전의 추세는 TrendForecaster 가 예측 경보(ForecastEvent)로 알린다.
 *
 * <p>알람 합리화(ISA-18.2)를 위해 새 알람을 내기 전에 세 가지를 본다.
 * <ul>
 *   <li>배치 단계: 단계를 알면 단계별 기준을 쓴다 (유화 중 75C 는 정상, 대기 중 75C 는 이상).
 *       단계가 바뀐 직후 유예 시간에는 단계별 기준으로 새 알람을 내지 않는다.</li>
 *   <li>지속 조건: 기준을 넘은 상태가 정해진 시간 이상 이어져야 낸다 (규칙의 delay).</li>
 *   <li>일시 억제: 작업자가 정비 등으로 억제해 둔 설비·지표면 내지 않는다.</li>
 * </ul>
 * 이미 진행 중인 알람의 추적·해제는 위 조건과 무관하게 계속한다.
 */
@Service
public class AlarmService {

    private static final Logger log = LoggerFactory.getLogger(AlarmService.class);

    private final AlarmRules rules;
    private final AlarmRepository repository;
    private final ApplicationEventPublisher events;
    private final TrendForecaster forecaster;
    private final BatchStateTracker batches;
    private final AlarmShelfService shelves;
    /** 지속 조건 대기 중인 설비·지표 → 기준을 처음 넘은 측정 시각 */
    private final Map<String, Instant> pendingSince = new ConcurrentHashMap<>();

    public AlarmService(AlarmRules rules, AlarmRepository repository, ApplicationEventPublisher events,
                        TrendForecaster forecaster, BatchStateTracker batches, AlarmShelfService shelves) {
        this.rules = rules;
        this.repository = repository;
        this.events = events;
        this.forecaster = forecaster;
        this.batches = batches;
        this.shelves = shelves;
    }

    @Transactional
    public void evaluate(SensorReading r) {
        Optional<BatchState> batch = batches.current(r.getEquipmentId());
        String phase = batch.map(BatchState::phase).orElse(null);
        Optional<Threshold> rule = rules.find(r.getEquipmentType(), r.getMetric(), phase);
        if (rule.isEmpty()) {
            return;
        }
        Threshold threshold = rule.get();
        boolean phaseRule = rules.phaseRule(r.getEquipmentType(), r.getMetric(), phase).isPresent();
        boolean inGrace = phaseRule && batch.get().secondsInPhase(r.getMeasuredAt()) < rules.phaseGrace().toSeconds();
        String key = r.getEquipmentId() + ":" + r.getMetric();
        double value = r.getValue();
        Optional<Threshold.Breach> breach = threshold.evaluate(value);
        Optional<Alarm> active = repository.findFirstByEquipmentIdAndMetricAndStatus(
                r.getEquipmentId(), r.getMetric(), AlarmStatus.ACTIVE);

        boolean activeNow;
        Alarm current = null;
        if (active.isEmpty()) {
            activeNow = false;
            if (breach.isEmpty()) {
                pendingSince.remove(key);
            } else if (mayRaise(r, threshold, key, inGrace)) {
                activeNow = true;
                pendingSince.remove(key);
                Alarm alarm = Alarm.raise(r.getEquipmentId(), r.getEquipmentType(), r.getMetric(), r.getUnit(),
                        breach.get(), value, r.getMeasuredAt());
                batch.ifPresent(b -> alarm.inBatch(b.phase(), b.batchId()));
                current = repository.save(alarm);
                log.warn("[ALARM RAISED] #{} {}{}", current.getId(), current.getMessage(),
                        phase == null ? "" : " phase " + phase);
                events.publishEvent(new AlarmEvent(AlarmEvent.Type.RAISED, current));
            }
        } else {
            activeNow = true;
            Alarm alarm = active.get();
            current = alarm;
            alarm.track(value, r.getMeasuredAt());
            boolean shelved = shelves.shelfFor(r.getEquipmentId(), r.getMetric(), r.getMeasuredAt()).isPresent();
            if (breach.isPresent() && !shelved && alarm.escalate(breach.get(), value, r.getMeasuredAt())) {
                log.warn("[ALARM ESCALATED] #{} {}", alarm.getId(), alarm.getMessage());
                events.publishEvent(new AlarmEvent(AlarmEvent.Type.ESCALATED, alarm));
            } else if (breach.isEmpty() && threshold.isClear(value)) {
                activeNow = false;
                alarm.clear(r.getMeasuredAt());
                log.info("[ALARM CLEARED] #{} {} {} back to {} (peak {})",
                        alarm.getId(), alarm.getEquipmentId(), alarm.getMetric(), value, alarm.getPeakValue());
                events.publishEvent(new AlarmEvent(AlarmEvent.Type.CLEARED, alarm));
            }
        }

        // 기준을 넘기 전에 추세로 먼저 알린다. 값이 목표를 향해 움직이는 단계(가열·냉각)와 전환 직후에는 하지 않는다
        if (inGrace || rules.isTransitional(phase)) {
            return;
        }
        Alarm raisedOrActive = current;
        forecaster.observe(r.getEquipmentId(), r.getEquipmentType(), r.getMetric(), r.getUnit(),
                r.getMeasuredAt(), value, threshold, activeNow).ifPresent(e -> {
            Forecast f = e.forecast();
            if (e.leadSeconds() != null && raisedOrActive != null) {
                // 알람 이벤트는 커밋 후에 직렬화되므로 여기서 남긴 값이 화면·에이전트에도 함께 간다
                raisedOrActive.markForecast(e.leadSeconds());
            }
            switch (e.type()) {
                case RAISED -> log.warn("[FORECAST] {} {} {} -> {} in ~{}s (slope {}/min)", f.equipmentId(),
                        f.metric(), f.currentValue(), f.limit(), f.secondsToLimit(), f.slopePerMinute());
                case CLEARED -> log.info("[FORECAST CLEARED] {} {} ({}{})", f.equipmentId(), f.metric(), e.reason(),
                        e.leadSeconds() == null ? "" : ", predicted " + e.leadSeconds() + "s before the alarm");
                default -> { }
            }
            events.publishEvent(e);
        });
    }

    /** 새 알람을 내도 되는지: 단계 전환 유예 · 일시 억제 · 지속 조건. */
    private boolean mayRaise(SensorReading r, Threshold threshold, String key, boolean inGrace) {
        if (inGrace) {
            return false;
        }
        if (shelves.shelfFor(r.getEquipmentId(), r.getMetric(), r.getMeasuredAt()).isPresent()) {
            pendingSince.remove(key);
            return false;
        }
        int delay = threshold.delaySeconds();
        if (delay == 0) {
            return true;
        }
        Instant since = pendingSince.computeIfAbsent(key, k -> r.getMeasuredAt());
        return Duration.between(since, r.getMeasuredAt()).toSeconds() >= delay;
    }

    /** 배치 단계가 바뀌면 그 설비의 지속 조건 대기와 추세 창을 버린다 (단계마다 정상 수준이 다르다). */
    public void onPhaseChange(BatchPhaseEvent e) {
        String equipmentId = e.current().equipmentId();
        pendingSince.keySet().removeIf(k -> k.startsWith(equipmentId + ":"));
        forecaster.reset(equipmentId).forEach(events::publishEvent);
    }

    @Transactional(readOnly = true)
    public List<Alarm> find(AlarmStatus status) {
        return status == null
                ? repository.findTop50ByOrderByRaisedAtDesc()
                : repository.findByStatusOrderByRaisedAtDesc(status);
    }

    @Transactional(readOnly = true)
    public Optional<Alarm> findById(Long id) {
        return repository.findById(id);
    }
}
