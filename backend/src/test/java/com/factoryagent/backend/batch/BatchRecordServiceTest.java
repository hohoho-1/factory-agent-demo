package com.factoryagent.backend.batch;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.AlarmRepository;
import com.factoryagent.backend.alarm.Severity;
import com.factoryagent.backend.alarm.Threshold;
import com.factoryagent.backend.control.SetpointChangeRepository;
import com.factoryagent.backend.telemetry.ReadingsSavedEvent;
import com.factoryagent.backend.telemetry.SensorReading;
import com.factoryagent.backend.workorder.WorkOrder;
import com.factoryagent.backend.workorder.WorkOrderRepository;
import com.factoryagent.backend.workorder.WorkOrderRequest;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class BatchRecordServiceTest {

    private static final Instant T0 = Instant.parse("2026-10-20T10:00:00Z");

    private final BatchRunRepository runs = mock(BatchRunRepository.class);
    private final BatchStateTracker tracker = new BatchStateTracker();
    private final BatchRecordService service = new BatchRecordService(runs, tracker, mock(AlarmRepository.class),
            mock(WorkOrderRepository.class), mock(SetpointChangeRepository.class));
    private final Map<String, BatchRun> stored = new HashMap<>();

    BatchRecordServiceTest() {
        when(runs.save(any(BatchRun.class))).thenAnswer(inv -> {
            BatchRun r = inv.getArgument(0);
            stored.put(r.getBatchId(), r);
            return r;
        });
        when(runs.findByBatchId(anyString())).thenAnswer(inv -> Optional.ofNullable(stored.get(inv.<String>getArgument(0))));
    }

    private void phase(String phase, String batchId, int second) {
        tracker.observe("MIXER-01", Map.of("batchPhase", phase, "batchId", batchId == null ? "" : batchId,
                "recipe", "크림 베이스 A"), T0.plusSeconds(second)).ifPresent(service::onPhase);
    }

    private void temperature(double value, int second) {
        Instant at = T0.plusSeconds(second);
        service.onReadings(new ReadingsSavedEvent(List.of(
                new SensorReading("MIXER-01", "MIXER", "temperature", value, "C", at, at))));
    }

    @Test
    void recordsPhasesWithDurationsAndRanges() {
        phase("IDLE", null, 0);
        phase("HEATING", "B-1020-01", 10);
        temperature(30, 11);
        temperature(74, 50);
        phase("EMULSIFYING", "B-1020-01", 55);
        temperature(75.5, 60);
        temperature(73.2, 80);
        phase("IDLE", null, 115);

        BatchRun run = stored.get("B-1020-01");
        assertThat(run.getStatus()).isEqualTo(BatchRun.Status.COMPLETED);
        assertThat(run.getRecipe()).isEqualTo("크림 베이스 A");
        assertThat(run.getEndedAt()).isEqualTo(T0.plusSeconds(115));
        assertThat(run.getPhases()).extracting(BatchRun.PhaseLog::phase).containsExactly("HEATING", "EMULSIFYING");
        BatchRun.PhaseLog heating = run.getPhases().get(0);
        assertThat(heating.seconds()).isEqualTo(45);
        assertThat(heating.metrics().get("temperature")).containsExactly(30, 74);
        assertThat(run.getPhases().get(1).metrics().get("temperature")).containsExactly(73.2, 75.5);
    }

    @Test
    void readingsOutsideABatchAreNotCollected() {
        phase("IDLE", null, 0);
        temperature(25, 1);
        phase("CHARGING", "B-1020-02", 5);
        temperature(28, 6);
        phase("IDLE", null, 25);
        assertThat(stored.get("B-1020-02").getPhases().get(0).metrics().get("temperature")).containsExactly(28, 28);
    }

    @Test
    void verdictReflectsAlarmsAndOpenActions() {
        BatchRun run = BatchRun.start(new BatchState("MIXER-01", "CHARGING", "B-1", "r", T0));
        assertThat(BatchRecordService.verdict(run, List.of(), List.of()).level()).isEqualTo("RUNNING");
        run.advance(null, T0.plusSeconds(200), Map.of());
        assertThat(BatchRecordService.verdict(run, List.of(), List.of()).level()).isEqualTo("OK");

        Alarm alarm = Alarm.raise("MIXER-01", "MIXER", "temperature", "C",
                new Threshold.Breach(Severity.WARNING, Threshold.Direction.LOW, 68), 66, T0.plusSeconds(90));
        ReflectionTestUtils.setField(alarm, "id", 5L);
        WorkOrder wo = WorkOrder.of(alarm, new WorkOrderRequest("t", "s", "b", "llm", List.of(), List.of(), null));
        ReflectionTestUtils.setField(wo, "id", 9L);

        BatchRecordService.Verdict hold = BatchRecordService.verdict(run, List.of(alarm), List.of(wo));
        assertThat(hold.level()).isEqualTo("HOLD");
        assertThat(hold.openActions()).isEqualTo(1);

        wo.complete("kim", "스팀 밸브 고착", "밸브 교체", com.factoryagent.backend.workorder.ActionOutcome.RESOLVED,
                T0.plusSeconds(150));
        assertThat(BatchRecordService.verdict(run, List.of(alarm), List.of(wo)).level()).isEqualTo("REVIEW");
    }
}
