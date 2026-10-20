package com.factoryagent.backend.alarm;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.ConstructorBinding;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * application.yml 의 app.alarm.
 *
 * @param rules              설비 유형 → 지표 → 임계값 (배치 단계를 모를 때의 기본 기준)
 * @param phaseRules         설비 유형 → 지표 → 배치 단계 → 임계값. 단계를 알면 기본 기준 대신 이것을 쓴다
 * @param phaseGrace         단계가 바뀐 직후 이 시간 동안은 단계별 기준으로 새 알람을 내지 않는다 (전환 순간의 값 튐)
 * @param transitionalPhases 값이 목표를 향해 움직이는 게 정상인 단계(가열·냉각). 이 단계에서는 추세 예측을 하지 않는다
 */
@ConfigurationProperties(prefix = "app.alarm")
public record AlarmRules(Map<String, Map<String, Threshold>> rules,
                         Map<String, Map<String, Map<String, Threshold>>> phaseRules,
                         Duration phaseGrace,
                         List<String> transitionalPhases) {

    @ConstructorBinding
    public AlarmRules {
        rules = rules == null ? Map.of() : rules;
        phaseRules = phaseRules == null ? Map.of() : phaseRules;
        phaseGrace = phaseGrace == null ? Duration.ofSeconds(10) : phaseGrace;
        transitionalPhases = transitionalPhases == null ? List.of() : List.copyOf(transitionalPhases);
    }

    public AlarmRules(Map<String, Map<String, Threshold>> rules) {
        this(rules, null, null, null);
    }

    public Optional<Threshold> find(String equipmentType, String metric) {
        return Optional.ofNullable(rules.getOrDefault(equipmentType, Map.of()).get(metric));
    }

    /** 이 지표에 단계별 기준이 있고 지금 단계의 기준이 정의돼 있으면 그것, 아니면 기본 기준. */
    public Optional<Threshold> find(String equipmentType, String metric, String phase) {
        return phaseRule(equipmentType, metric, phase).or(() -> find(equipmentType, metric));
    }

    public Optional<Threshold> phaseRule(String equipmentType, String metric, String phase) {
        if (phase == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(phaseRules.getOrDefault(equipmentType, Map.of())
                .getOrDefault(metric, Map.of()).get(phase));
    }

    public boolean isTransitional(String phase) {
        return phase != null && transitionalPhases.contains(phase);
    }
}
