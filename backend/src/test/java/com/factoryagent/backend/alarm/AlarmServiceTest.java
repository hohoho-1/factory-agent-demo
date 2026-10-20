package com.factoryagent.backend.alarm;

import com.factoryagent.backend.batch.BatchStateTracker;
import com.factoryagent.backend.forecast.TrendForecaster;
import com.factoryagent.backend.telemetry.SensorReading;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.context.ApplicationEventPublisher;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** 알람 합리화: 배치 단계별 기준 · 전환 직후 유예 · 지속 조건 · 일시 억제. */
class AlarmServiceTest {

    private static final Instant T0 = Instant.parse("2026-10-20T10:00:00Z");
    private static final Threshold DEFAULT_TEMP = new Threshold(50.0, 60.0, null, null, 5);

    private final AlarmRules rules = new AlarmRules(
            Map.of("MIXER", Map.of("temperature", DEFAULT_TEMP)),
            Map.of("MIXER", Map.of("temperature", Map.of(
                    "IDLE", new Threshold(50.0, 60.0, null, null, 5),
                    "EMULSIFYING", new Threshold(82.0, 88.0, 68.0, 62.0, 5)))),
            Duration.ofSeconds(10), List.of("HEATING", "COOLING"));
    private final AlarmRepository repository = mock(AlarmRepository.class);
    private final ApplicationEventPublisher events = mock(ApplicationEventPublisher.class);
    private final AlarmShelfService shelves = mock(AlarmShelfService.class);
    private final BatchStateTracker batches = new BatchStateTracker();
    private final AlarmService service = new AlarmService(rules, repository, events, new TrendForecaster(),
            batches, shelves);

    AlarmServiceTest() {
        when(repository.findFirstByEquipmentIdAndMetricAndStatus(anyString(), anyString(), any()))
                .thenReturn(Optional.empty());
        when(repository.save(any(Alarm.class))).thenAnswer(inv -> inv.getArgument(0));
        when(shelves.shelfFor(anyString(), anyString(), any())).thenReturn(Optional.empty());
    }

    private void phase(String phase, String batchId, Instant at) {
        batches.observe("MIXER-01", Map.of("batchPhase", phase, "batchId", batchId == null ? "" : batchId), at);
    }

    /** 같은 값이 seconds 초 동안 이어진다. */
    private void hold(double value, Instant from, int seconds) {
        for (int s = 0; s <= seconds; s++) {
            Instant at = from.plusSeconds(s);
            service.evaluate(new SensorReading("MIXER-01", "MIXER", "temperature", value, "C", at, at));
        }
    }

    private List<Alarm> raised() {
        ArgumentCaptor<Alarm> saved = ArgumentCaptor.forClass(Alarm.class);
        verify(repository, org.mockito.Mockito.atLeast(0)).save(saved.capture());
        return saved.getAllValues();
    }

    @Test
    void sameTemperatureIsNormalWhileEmulsifyingButAnAlarmWhenIdle() {
        phase("EMULSIFYING", "B-1020-01", T0.minusSeconds(60));
        hold(75.0, T0, 10);
        assertThat(raised()).isEmpty();

        phase("IDLE", null, T0.plusSeconds(20));
        hold(75.0, T0.plusSeconds(20), 20);  // 유예 10초 + 지속 5초가 지나면 알람
        assertThat(raised()).hasSize(1);
        assertThat(raised().get(0).getBatchPhase()).isEqualTo("IDLE");
        assertThat(raised().get(0).getSeverity()).isEqualTo(Severity.CRITICAL);
    }

    @Test
    void withoutPhaseTheDefaultRuleRaisesAFalseAlarmWhileHeating() {
        hold(75.0, T0, 6);  // 단계를 모르면 상온 기준(>=50) → 가열만 해도 알람
        assertThat(raised()).hasSize(1);
        assertThat(raised().get(0).getBatchPhase()).isNull();
    }

    @Test
    void lowTemperatureDuringEmulsifyingRaisesWithBatchContext() {
        phase("EMULSIFYING", "B-1020-02", T0.minusSeconds(60));
        hold(66.0, T0, 6);
        Alarm alarm = raised().get(0);
        assertThat(alarm.getSeverity()).isEqualTo(Severity.WARNING);
        assertThat(alarm.getDirection()).isEqualTo(Threshold.Direction.LOW);
        assertThat(alarm.getBatchId()).isEqualTo("B-1020-02");
        verify(events).publishEvent(any(AlarmEvent.class));
    }

    @Test
    void graceAfterPhaseChangeHoldsBackNewAlarms() {
        phase("EMULSIFYING", "B-1020-03", T0);   // 방금 유화로 넘어옴, 아직 68C 에 못 미침
        hold(66.0, T0, 9);
        assertThat(raised()).isEmpty();
        hold(66.0, T0.plusSeconds(10), 6);       // 유예가 끝나고 5초 지속
        assertThat(raised()).hasSize(1);
    }

    @Test
    void breachMustLastForTheDelay() {
        phase("IDLE", null, T0.minusSeconds(60));
        hold(55.0, T0, 3);
        hold(45.0, T0.plusSeconds(4), 0);         // 한 번 내려오면 지속 시간이 처음부터 다시
        hold(55.0, T0.plusSeconds(5), 4);
        assertThat(raised()).isEmpty();
        hold(55.0, T0.plusSeconds(10), 0);
        assertThat(raised()).hasSize(1);
    }

    @Test
    void shelvedEquipmentDoesNotRaise() {
        when(shelves.shelfFor(eq("MIXER-01"), eq("temperature"), any())).thenReturn(Optional.of(
                AlarmShelf.shelve("MIXER-01", null, "베어링 교체 중", "kim", T0, T0.plusSeconds(600))));
        hold(75.0, T0, 10);
        verify(repository, never()).save(any(Alarm.class));
    }

    @Test
    void phaseChangeResetsPendingDelay() {
        phase("IDLE", null, T0.minusSeconds(60));
        hold(55.0, T0, 3);
        phase("EMULSIFYING", "B-1020-04", T0.plusSeconds(4));
        service.onPhaseChange(new com.factoryagent.backend.batch.BatchPhaseEvent(null,
                batches.current("MIXER-01").orElseThrow()));
        hold(75.0, T0.plusSeconds(4), 15);
        verify(repository, times(0)).save(any(Alarm.class));
    }

    @Test
    void shelfCoversEquipmentOrSingleMetricUntilItExpires() {
        AlarmShelf all = AlarmShelf.shelve("MIXER-01", null, "정비", "kim", T0, T0.plusSeconds(60));
        AlarmShelf one = AlarmShelf.shelve("MIXER-01", "vibration", "정비", "kim", T0, T0.plusSeconds(60));
        assertThat(all.covers("MIXER-01", "temperature", T0.plusSeconds(10))).isTrue();
        assertThat(one.covers("MIXER-01", "temperature", T0.plusSeconds(10))).isFalse();
        assertThat(one.covers("MIXER-01", "vibration", T0.plusSeconds(61))).isFalse();
        one.release("lee", T0.plusSeconds(20));
        assertThat(one.covers("MIXER-01", "vibration", T0.plusSeconds(30))).isFalse();
    }
}
