package com.factoryagent.backend.alarm;

import org.junit.jupiter.api.Test;
import org.springframework.boot.context.properties.bind.Binder;
import org.springframework.boot.context.properties.source.MapConfigurationPropertySource;

import java.time.Duration;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/** application.yml 형식의 app.alarm 이 레코드로 묶이는지 (생성자가 여럿이라 바인딩 생성자를 지정해 둠). */
class AlarmRulesBindingTest {

    @Test
    void bindsDefaultAndPhaseRulesWithDelay() {
        Map<String, String> props = Map.of(
                "app.alarm.rules[MIXER].temperature.warn-high", "50",
                "app.alarm.rules[MIXER].temperature.delay", "5",
                "app.alarm.phase-rules[MIXER].temperature.EMULSIFYING.warn-low", "68",
                "app.alarm.phase-rules[MIXER].temperature.EMULSIFYING.crit-low", "62",
                "app.alarm.phase-grace", "10s",
                "app.alarm.transitional-phases[0]", "HEATING");

        AlarmRules rules = new Binder(new MapConfigurationPropertySource(props))
                .bind("app.alarm", AlarmRules.class).get();

        assertThat(rules.find("MIXER", "temperature").orElseThrow().delaySeconds()).isEqualTo(5);
        assertThat(rules.find("MIXER", "temperature", "EMULSIFYING").orElseThrow().warnLow()).isEqualTo(68.0);
        assertThat(rules.find("MIXER", "temperature", "IDLE").orElseThrow().warnHigh()).isEqualTo(50.0);
        assertThat(rules.phaseGrace()).isEqualTo(Duration.ofSeconds(10));
        assertThat(rules.isTransitional("HEATING")).isTrue();
    }
}
