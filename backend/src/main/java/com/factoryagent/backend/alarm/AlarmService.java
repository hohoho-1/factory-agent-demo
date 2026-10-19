package com.factoryagent.backend.alarm;

import com.factoryagent.backend.forecast.Forecast;
import com.factoryagent.backend.forecast.TrendForecaster;
import com.factoryagent.backend.telemetry.SensorReading;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

/**
 * 측정값을 임계값 규칙과 비교해 알람을 발생 · 상승 · 해제하고, 상태 변화를 AlarmEvent 로 알린다.
 * 기준을 넘기 전의 추세는 TrendForecaster 가 예측 경보(ForecastEvent)로 알린다.
 */
@Service
public class AlarmService {

    private static final Logger log = LoggerFactory.getLogger(AlarmService.class);

    private final AlarmRules rules;
    private final AlarmRepository repository;
    private final ApplicationEventPublisher events;
    private final TrendForecaster forecaster;

    public AlarmService(AlarmRules rules, AlarmRepository repository, ApplicationEventPublisher events,
                        TrendForecaster forecaster) {
        this.rules = rules;
        this.repository = repository;
        this.events = events;
        this.forecaster = forecaster;
    }

    @Transactional
    public void evaluate(SensorReading r) {
        Optional<Threshold> rule = rules.find(r.getEquipmentType(), r.getMetric());
        if (rule.isEmpty()) {
            return;
        }
        Threshold threshold = rule.get();
        double value = r.getValue();
        Optional<Threshold.Breach> breach = threshold.evaluate(value);
        Optional<Alarm> active = repository.findFirstByEquipmentIdAndMetricAndStatus(
                r.getEquipmentId(), r.getMetric(), AlarmStatus.ACTIVE);

        boolean activeNow;
        Alarm current = null;
        if (active.isEmpty()) {
            activeNow = breach.isPresent();
            if (breach.isPresent()) {
                current = repository.save(Alarm.raise(r.getEquipmentId(), r.getEquipmentType(),
                        r.getMetric(), r.getUnit(), breach.get(), value, r.getMeasuredAt()));
                log.warn("[ALARM RAISED] #{} {}", current.getId(), current.getMessage());
                events.publishEvent(new AlarmEvent(AlarmEvent.Type.RAISED, current));
            }
        } else {
            activeNow = true;
            Alarm alarm = active.get();
            current = alarm;
            alarm.track(value, r.getMeasuredAt());
            if (breach.isPresent() && alarm.escalate(breach.get(), value, r.getMeasuredAt())) {
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

        // 기준을 넘기 전에 추세로 먼저 알린다 (실제 알람이 진행 중이면 예측은 내린다)
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
