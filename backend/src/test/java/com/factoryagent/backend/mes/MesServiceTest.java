package com.factoryagent.backend.mes;

import com.factoryagent.backend.batch.BatchPhaseEvent;
import com.factoryagent.backend.batch.BatchState;
import com.factoryagent.backend.batch.BatchStateTracker;
import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class MesServiceTest {

    private static final Instant T0 = Instant.parse("2026-11-19T05:00:00Z");

    private final ProductionJobRepository jobs = mock(ProductionJobRepository.class);
    private final JobBatchRepository batches = mock(JobBatchRepository.class);
    private final BatchStateTracker tracker = mock(BatchStateTracker.class);
    private final ApplicationEventPublisher events = mock(ApplicationEventPublisher.class);
    private final MesService service = new MesService(jobs, batches, tracker, events,
            Optional.of(Clock.fixed(T0, ZoneOffset.UTC)));
    private final Map<String, JobBatch> byBatchId = new HashMap<>();
    private long nextId = 1;

    MesServiceTest() {
        when(jobs.save(any(ProductionJob.class))).thenAnswer(inv -> {
            ProductionJob j = inv.getArgument(0);
            if (j.getId() == null) {
                ReflectionTestUtils.setField(j, "id", 10L);
            }
            for (JobBatch b : j.getBatches()) {
                if (b.getId() == null) {
                    ReflectionTestUtils.setField(b, "id", nextId++);
                }
                byBatchId.put(b.getBatchId(), b);
            }
            return j;
        });
        when(jobs.findByErpOrderNo(anyString())).thenReturn(Optional.empty());
        when(batches.findByBatchId(anyString())).thenAnswer(inv -> Optional.ofNullable(byBatchId.get(inv.getArgument(0))));
        when(batches.save(any(JobBatch.class))).thenAnswer(inv -> inv.getArgument(0));
        when(tracker.current("MIXER-01")).thenReturn(Optional.empty());
    }

    private ProductionJob job(int qty, int batchCount) {
        ProductionJob j = service.receive(new MesService.JobRequest("PRD-0001", "CAP-A30", "캡슐 세제 A 30개입", qty,
                batchCount));
        when(jobs.findById(10L)).thenReturn(Optional.of(j));
        return j;
    }

    private void phase(String prevBatch, String prevPhase, String batch, String phase) {
        BatchState prev = prevBatch == null && prevPhase == null ? null
                : new BatchState("MIXER-01", prevPhase, prevBatch, "r", T0);
        service.onPhase(new BatchPhaseEvent(prev, new BatchState("MIXER-01", phase, batch, "r", T0.plusSeconds(190))));
    }

    @Test
    void batchesSplitTheQuantityExactly() {
        ProductionJob j = job(10, 3);
        assertThat(j.qtyOfBatch(1) + j.qtyOfBatch(2) + j.qtyOfBatch(3)).isEqualTo(10);
        assertThat(j.qtyOfBatch(1)).isEqualTo(4);
        assertThat(j.qtyOfBatch(3)).isEqualTo(3);
    }

    @Test
    void startRunCompleteAndReport() {
        ProductionJob j = job(4444, 2);
        JobBatch first = service.startNextBatch(10L, "kim");
        assertThat(first.getBatchId()).isEqualTo("PRD-0001-01");
        assertThat(first.getQty()).isEqualTo(2222);
        verify(events).publishEvent(new JobBatchRequestedEvent(first.getId(), "MIXER-01", "PRD-0001-01",
                "캡슐 세제 A 30개입", "kim"));
        // 한 지시에서 배치가 진행 중이면 다음 배치를 열 수 없다
        assertThatThrownBy(() -> service.startNextBatch(10L, "kim")).isInstanceOf(IllegalStateException.class);

        service.onCommandResult(first.getId(), "APPLIED", "PLC 명령 실행");
        when(batches.findById(first.getId())).thenReturn(Optional.of(first));
        phase(null, null, "PRD-0001-01", "CHARGING");
        assertThat(first.getStatus()).isEqualTo(JobBatch.Status.RUNNING);

        phase("PRD-0001-01", "DISCHARGING", null, "IDLE");  // 배치 종료
        assertThat(first.getStatus()).isEqualTo(JobBatch.Status.COMPLETED);
        assertThat(j.getBatchesDone()).isEqualTo(1);
        assertThat(j.getProducedQty()).isEqualTo(2222);
        verify(events).publishEvent(new JobBatchCompletedEvent("PRD-0001-01"));

        JobBatch second = service.startNextBatch(10L, "kim");
        phase("PRD-0001-02", "DISCHARGING", null, "IDLE");
        assertThat(second.getStatus()).isEqualTo(JobBatch.Status.COMPLETED);
        assertThat(j.getStatus()).isEqualTo(ProductionJob.Status.COMPLETED);
        assertThat(j.getProducedQty()).isEqualTo(4444);
        assertThatThrownBy(() -> service.startNextBatch(10L, "kim")).hasMessageContaining("모두 마친");
    }

    @Test
    void busyMixerBlocksBeforeReachingThePlc() {
        job(2222, 1);
        when(tracker.current("MIXER-01")).thenReturn(Optional.of(
                new BatchState("MIXER-01", "HEATING", "B-1119-090000", "크림 베이스 A", T0)));
        assertThatThrownBy(() -> service.startNextBatch(10L, "kim")).hasMessageContaining("B-1119-090000");
    }

    @Test
    void plcRejectionFailsTheBatchAndAllowsARetryWithANewNumber() {
        ProductionJob j = job(2222, 1);
        JobBatch first = service.startNextBatch(10L, "kim");
        when(batches.findById(first.getId())).thenReturn(Optional.of(first));
        service.onCommandResult(first.getId(), "INTERLOCKED", "배치 진행 중이라 새 배치를 시작할 수 없습니다");
        assertThat(first.getStatus()).isEqualTo(JobBatch.Status.FAILED);
        assertThat(first.getMessage()).contains("배치 진행 중");

        JobBatch retry = service.startNextBatch(10L, "kim");
        assertThat(retry.getBatchId()).isEqualTo("PRD-0001-02");   // 실패 기록은 남기고 번호를 새로
        assertThat(retry.getQty()).isEqualTo(2222);
        assertThat(j.getBatchesDone()).isZero();
    }

    @Test
    void rejectsMalformedJobs() {
        assertThatThrownBy(() -> service.receive(new MesService.JobRequest("PRD-1", "CAP-A30", "x", 3, 5)))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
