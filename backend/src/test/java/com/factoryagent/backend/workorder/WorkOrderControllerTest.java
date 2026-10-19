package com.factoryagent.backend.workorder;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.AlarmService;
import com.factoryagent.backend.alarm.Severity;
import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import java.util.List;
import java.util.Optional;

import static com.factoryagent.backend.workorder.WorkOrderFixtures.alarm;
import static com.factoryagent.backend.workorder.WorkOrderFixtures.workOrder;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class WorkOrderControllerTest {

    private final WorkOrderRepository repository = mock(WorkOrderRepository.class);
    private final ApplicationEventPublisher events = mock(ApplicationEventPublisher.class);
    private final WorkOrderController controller =
            new WorkOrderController(mock(AlarmService.class), repository, events);

    private final Alarm alarm = alarm(1, "MIXER-01", "vibration", Severity.CRITICAL);

    WorkOrderControllerTest() {
        when(repository.save(any(WorkOrder.class))).thenAnswer(inv -> inv.getArgument(0));
    }

    @Test
    void completingOneWorkOrderSupersedesOpenSiblingsOfSameAlarm() {
        WorkOrder warning = workOrder(10, alarm);
        WorkOrder critical = workOrder(11, alarm);
        when(repository.findById(11L)).thenReturn(Optional.of(critical));
        when(repository.findByAlarmIdOrderByCreatedAtDesc(1L)).thenReturn(List.of(critical, warning));

        ResponseEntity<WorkOrder> res = controller.complete(11L,
                new ActionResultRequest("kim", "베어링", "그리스 보충", ActionOutcome.RESOLVED));

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(critical.getStatus()).isEqualTo(WorkOrderStatus.COMPLETED);
        assertThat(warning.getStatus()).isEqualTo(WorkOrderStatus.SUPERSEDED);
        assertThat(warning.getSupersededBy()).isEqualTo(11L);
        verify(events, times(2)).publishEvent(any(WorkOrderUpdatedEvent.class));
    }

    @Test
    void completeRejectsMissingActionAndClosedWorkOrders() {
        assertThat(controller.complete(11L, new ActionResultRequest("kim", null, " ", ActionOutcome.RESOLVED))
                .getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);

        WorkOrder superseded = workOrder(10, alarm);
        superseded.supersede(11L, java.time.Instant.now());
        when(repository.findById(10L)).thenReturn(Optional.of(superseded));
        assertThat(controller.complete(10L, new ActionResultRequest("kim", null, "조치", ActionOutcome.RESOLVED))
                .getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        verify(events, never()).publishEvent(any());
    }

    @Test
    void historyPutsSameEquipmentFirstThenSameTypeOthersOnlyWhenTypeGiven() {
        WorkOrder same = WorkOrderFixtures.completed(20, alarm, "베어링", ActionOutcome.RESOLVED, 60);
        WorkOrder other = WorkOrderFixtures.completed(21, alarm(2, "MIXER-02", "vibration", Severity.WARNING),
                "임펠러", ActionOutcome.RESOLVED, 60);
        when(repository.findTop5ByEquipmentIdAndMetricAndStatusAndAlarmIdNotOrderByCompletedAtDesc(
                "MIXER-01", "vibration", WorkOrderStatus.COMPLETED, 9L)).thenReturn(List.of(same));
        when(repository.findTop3ByEquipmentTypeAndEquipmentIdNotAndMetricAndStatusOrderByCompletedAtDesc(
                "MIXER", "MIXER-01", "vibration", WorkOrderStatus.COMPLETED)).thenReturn(List.of(other));

        assertThat(controller.history("MIXER-01", "vibration", 9L, "MIXER"))
                .extracting(WorkOrder::getId).containsExactly(20L, 21L);
        assertThat(controller.history("MIXER-01", "vibration", 9L, null))
                .extracting(WorkOrder::getId).containsExactly(20L);
    }

    @Test
    void completeWithBlankWorkerKeepsAcknowledgingWorker() {
        WorkOrder w = workOrder(10, alarm);
        w.acknowledge("홍길동", java.time.Instant.now());
        when(repository.findById(10L)).thenReturn(Optional.of(w));
        when(repository.findByAlarmIdOrderByCreatedAtDesc(1L)).thenReturn(List.of(w));

        controller.complete(10L, new ActionResultRequest(" ", null, "조치", ActionOutcome.RESOLVED));

        assertThat(w.getWorker()).isEqualTo("홍길동");
    }

    @Test
    void blankWorkerBecomesDefault() {
        WorkOrder w = workOrder(10, alarm);
        when(repository.findById(10L)).thenReturn(Optional.of(w));
        controller.acknowledge(10L, new AcknowledgeRequest("  "));
        assertThat(w.getWorker()).isEqualTo("현장 작업자");
    }
}
