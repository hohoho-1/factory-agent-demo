package com.factoryagent.backend.forecast;

import com.factoryagent.backend.alarm.Threshold;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.Random;

import static org.assertj.core.api.Assertions.assertThat;

/** 가상 센서와 같은 노이즈 모델(목표값으로 당기는 힘 + 균등 노이즈)로 예측을 확인한다. */
class TrendForecasterTest {

    private static final Threshold VIBRATION = new Threshold(4.5, 7.1, null, null);
    private static final Instant T0 = Instant.parse("2026-10-19T00:00:00Z");

    private TrendForecaster forecaster = new TrendForecaster();
    private Random random = new Random(42);

    private double target = 2.5;

    /** 가상 센서와 같은 모델: 목표값으로 당기는 힘 + 균등 노이즈. 서서히 오르는 이상은 목표값 자체가 drift 만큼씩 오른다. */
    private List<ForecastEvent> run(double start, double drift, int seconds, int offset) {
        List<ForecastEvent> events = new ArrayList<>();
        double v = start;
        for (int i = 0; i < seconds; i++) {
            target += drift;
            v += (target - v) * 0.1 + (random.nextDouble() * 0.3 - 0.15);
            boolean alarm = v >= 4.5;
            forecaster.observe("MIXER-01", "MIXER", "vibration", "mm/s", T0.plusSeconds(offset + i), v, VIBRATION, alarm)
                    .ifPresent(events::add);
            if (alarm) {
                break;
            }
        }
        return events;
    }

    @Test
    void normalNoiseDoesNotForecast() {
        // 시드 20개 × 10분 = 정상 운전 3시간 20분 동안 오경보 0건
        for (int seed = 1; seed <= 20; seed++) {
            forecaster = new TrendForecaster();
            random = new Random(seed);
            target = 2.5;
            assertThat(run(2.5, 0, 600, 0)).as("seed %d", seed).isEmpty();
        }
    }

    /** 실제처럼 2분 정상 운전으로 평소 수준을 배운 뒤 이상을 시작한다. */
    private double warmUp() {
        assertThat(run(2.5, 0, 120, 0)).isEmpty();
        return 2.5;
    }

    @Test
    void slowRiseIsForecastWellBeforeTheWarningAndClearedByTheAlarm() {
        List<ForecastEvent> events = run(warmUp(), 0.04, 200, 120);

        assertThat(events).first().satisfies(e -> {
            assertThat(e.type()).isEqualTo(ForecastEvent.Type.RAISED);
            assertThat(e.forecast().limit()).isEqualTo(4.5);
            assertThat(e.forecast().direction()).isEqualTo(Threshold.Direction.HIGH);
            assertThat(e.forecast().secondsToLimit()).isBetween(1L, TrendForecaster.HORIZON_SECONDS);
        });
        ForecastEvent last = events.get(events.size() - 1);
        assertThat(last.type()).isEqualTo(ForecastEvent.Type.CLEARED);
        assertThat(last.reason()).isEqualTo("ALARM");
        assertThat(last.leadSeconds()).isGreaterThanOrEqualTo(15L);
        assertThat(forecaster.current()).isEmpty();
    }

    @Test
    void forecastClearsWhenTheTrendTurnsAround() {
        List<ForecastEvent> rising = run(warmUp(), 0.04, 32, 120);
        assertThat(rising).extracting(ForecastEvent::type).contains(ForecastEvent.Type.RAISED);

        List<ForecastEvent> falling = run(forecaster.current().get(0).currentValue(), -0.08, 30, 152);
        assertThat(falling).last().satisfies(e -> {
            assertThat(e.type()).isEqualTo(ForecastEvent.Type.CLEARED);
            assertThat(e.reason()).isEqualTo("RECOVERED");
        });
    }

    @Test
    void lowSideUsesLowLimit() {
        Threshold speed = new Threshold(null, null, 100.0, 80.0);
        List<TrendForecaster.Sample> samples = new ArrayList<>();
        for (int i = 0; i < TrendForecaster.WINDOW; i++) {
            samples.add(new TrendForecaster.Sample(T0.plusSeconds(i), 120 - i * 0.3));
        }
        Optional<TrendForecaster.Prediction> p = TrendForecaster.predict(samples, 108.3, speed);
        assertThat(p).get().satisfies(pr -> {
            assertThat(pr.direction()).isEqualTo(Threshold.Direction.LOW);
            assertThat(pr.limit()).isEqualTo(100.0);
            assertThat(pr.secondsToLimit()).isEqualTo(28L);
        });
    }
}
