package com.factoryagent.backend.quality;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.AlarmRepository;
import com.factoryagent.backend.alarm.Severity;
import com.factoryagent.backend.alarm.Threshold;
import com.factoryagent.backend.workorder.WorkOrder;
import com.factoryagent.backend.workorder.WorkOrderRepository;
import com.factoryagent.backend.workorder.WorkOrderRequest;
import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.http.HttpStatus;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class QualityControllerTest {

    private static final Instant T0 = Instant.parse("2026-11-19T05:00:00Z");

    private final QualityAssessmentRepository repository = mock(QualityAssessmentRepository.class);
    private final WorkOrderRepository workOrders = mock(WorkOrderRepository.class);
    private final AlarmRepository alarms = mock(AlarmRepository.class);
    private final ApplicationEventPublisher events = mock(ApplicationEventPublisher.class);
    private final QualityController controller = new QualityController(repository, workOrders, alarms, events,
            Optional.of(Clock.fixed(T0, ZoneOffset.UTC)));

    QualityControllerTest() {
        when(repository.save(any(QualityAssessment.class))).thenAnswer(inv -> inv.getArgument(0));
    }

    private Alarm alarm(boolean inBatch) {
        Alarm a = Alarm.raise("MIXER-01", "MIXER", "temperature", "C",
                new Threshold.Breach(Severity.CRITICAL, Threshold.Direction.LOW, 62), 61, T0);
        ReflectionTestUtils.setField(a, "id", 5L);
        if (inBatch) {
            a.inBatch("EMULSIFYING", "B-1119-01");
        }
        WorkOrder wo = WorkOrder.of(a, new WorkOrderRequest("t", "s", "b", "llm", List.of(), List.of(), null));
        ReflectionTestUtils.setField(wo, "id", 9L);
        when(workOrders.findById(9L)).thenReturn(Optional.of(wo));
        when(alarms.findById(5L)).thenReturn(Optional.of(a));
        return a;
    }

    @Test
    void holdIsPendingUntilQualityTeamDecides() {
        alarm(true);
        QualityAssessment q = (QualityAssessment) controller.create(9L, new QualityController.AssessmentRequest(
                "HOLD", "유화 단계 온도 위험 이탈", "이유", "template")).getBody();
        assertThat(q.getStatus()).isEqualTo(QualityAssessment.Status.PENDING);
        assertThat(q.getBatchId()).isEqualTo("B-1119-01");
        assertThat(q.getBatchPhase()).isEqualTo("EMULSIFYING");
        verify(events).publishEvent(new QualityAssessmentEvent(q));

        when(repository.findById(1L)).thenReturn(Optional.of(q));
        controller.approve(1L, new QualityController.DecisionRequest("qa-lee", null));
        assertThat(q.getStatus()).isEqualTo(QualityAssessment.Status.APPROVED);
        assertThat(q.getDecidedBy()).isEqualTo("qa-lee");
        // 이미 결정된 판정은 다시 결정할 수 없다
        assertThat(controller.reject(1L, null).getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
    }

    @Test
    void lowerLevelsAreRecordedWithoutApproval() {
        alarm(true);
        QualityAssessment q = (QualityAssessment) controller.create(9L, new QualityController.AssessmentRequest(
                "INSPECT", "유화 단계 온도 경고 이탈", null, "template")).getBody();
        assertThat(q.getStatus()).isEqualTo(QualityAssessment.Status.RECORDED);
        when(repository.findById(2L)).thenReturn(Optional.of(q));
        assertThat(controller.approve(2L, null).getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
    }

    @Test
    void rejectsAlarmsOutsideABatchAndBadInput() {
        alarm(false);
        assertThat(controller.create(9L, new QualityController.AssessmentRequest("HOLD", "b", null, null))
                .getStatusCode()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
        alarm(true);
        assertThat(controller.create(9L, new QualityController.AssessmentRequest("BAD", "b", null, null))
                .getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(controller.create(9L, new QualityController.AssessmentRequest("HOLD", " ", null, null))
                .getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(controller.create(99L, new QualityController.AssessmentRequest("HOLD", "b", null, null))
                .getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        verify(repository, never()).save(any());
    }
}
