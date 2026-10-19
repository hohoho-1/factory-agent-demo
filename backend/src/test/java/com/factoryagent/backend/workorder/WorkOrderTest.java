package com.factoryagent.backend.workorder;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.Severity;
import org.junit.jupiter.api.Test;

import java.time.Instant;

import static com.factoryagent.backend.workorder.WorkOrderFixtures.alarm;
import static com.factoryagent.backend.workorder.WorkOrderFixtures.workOrder;
import static org.assertj.core.api.Assertions.assertThat;

class WorkOrderTest {

    private final Alarm alarm = alarm(1, "MIXER-01", "vibration", Severity.CRITICAL);

    @Test
    void newWorkOrderIsOpenAndCopiesAlarm() {
        WorkOrder w = workOrder(10, alarm);
        assertThat(w.getStatus()).isEqualTo(WorkOrderStatus.OPEN);
        assertThat(w.getAlarmId()).isEqualTo(1L);
        assertThat(w.getSeverity()).isEqualTo(Severity.CRITICAL);
    }

    @Test
    void requestSeverityWinsOverAlarmThatEscalatedMeanwhile() {
        WorkOrder w = WorkOrder.of(alarm, new WorkOrderRequest("t", "s", "b", "llm", java.util.List.of(),
                java.util.List.of(), Severity.WARNING));
        assertThat(w.getSeverity()).isEqualTo(Severity.WARNING);
    }

    @Test
    void acknowledgeOnlyOnce() {
        WorkOrder w = workOrder(10, alarm);
        assertThat(w.acknowledge("kim", Instant.now())).isTrue();
        assertThat(w.getStatus()).isEqualTo(WorkOrderStatus.ACKNOWLEDGED);
        assertThat(w.acknowledge("lee", Instant.now())).isFalse();
        assertThat(w.getWorker()).isEqualTo("kim");
    }

    @Test
    void completeWithoutAcknowledgeFillsAcknowledgedAt() {
        WorkOrder w = workOrder(10, alarm);
        Instant at = Instant.now();
        w.complete("kim", "베어링 윤활 부족", "그리스 보충", ActionOutcome.RESOLVED, at);
        assertThat(w.getStatus()).isEqualTo(WorkOrderStatus.COMPLETED);
        assertThat(w.getAcknowledgedAt()).isEqualTo(at);
        assertThat(w.getCompletedAt()).isEqualTo(at);
        assertThat(w.getRootCause()).isEqualTo("베어링 윤활 부족");
    }

    @Test
    void supersedeClosesOpenButNotClosedWorkOrders() {
        WorkOrder open = workOrder(10, alarm);
        assertThat(open.supersede(11L, Instant.now())).isTrue();
        assertThat(open.getStatus()).isEqualTo(WorkOrderStatus.SUPERSEDED);
        assertThat(open.getSupersededBy()).isEqualTo(11L);

        WorkOrder done = workOrder(12, alarm);
        done.complete("kim", null, "조치", ActionOutcome.PARTIAL, Instant.now());
        assertThat(done.supersede(11L, Instant.now())).isFalse();
        assertThat(done.getStatus()).isEqualTo(WorkOrderStatus.COMPLETED);
    }
}
