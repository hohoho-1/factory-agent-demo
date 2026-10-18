package com.factoryagent.backend.alarm;

import com.factoryagent.backend.telemetry.SensorReading;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;

/**
 * 측정값을 임계값 규칙과 비교해 알람을 발생 · 상승 · 해제한다.
 */
@Service
public class AlarmService {

    private static final Logger log = LoggerFactory.getLogger(AlarmService.class);

    private final AlarmRules rules;
    private final AlarmRepository repository;

    public AlarmService(AlarmRules rules, AlarmRepository repository) {
        this.rules = rules;
        this.repository = repository;
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

        if (active.isEmpty()) {
            breach.ifPresent(b -> {
                Alarm alarm = repository.save(Alarm.raise(r.getEquipmentId(), r.getEquipmentType(),
                        r.getMetric(), r.getUnit(), b, value, r.getMeasuredAt()));
                log.warn("[ALARM RAISED] #{} {}", alarm.getId(), alarm.getMessage());
            });
            return;
        }

        Alarm alarm = active.get();
        alarm.track(value, r.getMeasuredAt());
        if (breach.isPresent() && alarm.escalate(breach.get(), value, r.getMeasuredAt())) {
            log.warn("[ALARM ESCALATED] #{} {}", alarm.getId(), alarm.getMessage());
        } else if (breach.isEmpty() && threshold.isClear(value)) {
            alarm.clear(r.getMeasuredAt());
            log.info("[ALARM CLEARED] #{} {} {} back to {} (peak {})",
                    alarm.getId(), alarm.getEquipmentId(), alarm.getMetric(), value, alarm.getPeakValue());
        }
    }

    @Transactional(readOnly = true)
    public List<Alarm> find(AlarmStatus status) {
        return status == null
                ? repository.findTop50ByOrderByRaisedAtDesc()
                : repository.findByStatusOrderByRaisedAtDesc(status);
    }
}
