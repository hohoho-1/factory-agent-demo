package com.factoryagent.backend.alarm;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.Map;
import java.util.Optional;

/**
 * application.yml 의 app.alarm.rules — 설비 유형 → 지표 → 임계값.
 */
@ConfigurationProperties(prefix = "app.alarm")
public record AlarmRules(Map<String, Map<String, Threshold>> rules) {

    public AlarmRules {
        rules = rules == null ? Map.of() : rules;
    }

    public Optional<Threshold> find(String equipmentType, String metric) {
        return Optional.ofNullable(rules.getOrDefault(equipmentType, Map.of()).get(metric));
    }
}
