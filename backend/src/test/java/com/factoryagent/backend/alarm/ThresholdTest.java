package com.factoryagent.backend.alarm;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ThresholdTest {

    private final Threshold vibration = new Threshold(4.5, 7.1, null, null);
    private final Threshold speed = new Threshold(null, null, 100.0, 80.0);

    @Test
    void normalValueHasNoBreach() {
        assertThat(vibration.evaluate(2.5)).isEmpty();
        assertThat(speed.evaluate(120)).isEmpty();
    }

    @Test
    void highSideWarningAndCritical() {
        assertThat(vibration.evaluate(4.5)).get()
                .extracting(Threshold.Breach::severity).isEqualTo(Severity.WARNING);
        assertThat(vibration.evaluate(8.0)).get()
                .satisfies(b -> {
                    assertThat(b.severity()).isEqualTo(Severity.CRITICAL);
                    assertThat(b.limit()).isEqualTo(7.1);
                    assertThat(b.direction()).isEqualTo(Threshold.Direction.HIGH);
                });
    }

    @Test
    void lowSideWarningAndCritical() {
        assertThat(speed.evaluate(95)).get()
                .extracting(Threshold.Breach::severity).isEqualTo(Severity.WARNING);
        assertThat(speed.evaluate(70)).get()
                .extracting(Threshold.Breach::direction).isEqualTo(Threshold.Direction.LOW);
    }

    @Test
    void clearRequiresHysteresisMargin() {
        // 4.5 의 5% 안쪽(4.275) 미만이어야 해제
        assertThat(vibration.isClear(4.4)).isFalse();
        assertThat(vibration.isClear(4.2)).isTrue();
        // 100 의 5% 바깥(105) 초과여야 해제
        assertThat(speed.isClear(103)).isFalse();
        assertThat(speed.isClear(110)).isTrue();
    }
}
