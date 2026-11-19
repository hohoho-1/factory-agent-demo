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
    void verdictFirstThenExplanationLinksTheWorkOrder() {
        alarm(true);
        // 알람 직후: 지시서 없이 판정부터. 홀드면 바로 승인 대기
        QualityAssessment q = (QualityAssessment) controller.createForAlarm(5L, new QualityController.AssessmentRequest(
                "HOLD", "유화 단계 온도 위험 이탈", "템플릿 설명", "template")).getBody();
        assertThat(q.getWorkOrderId()).isNull();
        assertThat(q.getStatus()).isEqualTo(QualityAssessment.Status.PENDING);

        // 품질팀은 설명을 기다리지 않고 승인할 수 있다
        when(repository.findById(3L)).thenReturn(Optional.of(q));
        controller.approve(3L, new QualityController.DecisionRequest("qa-lee", null));

        // 지시서가 나오면 연결하고 설명만 바꾼다. 판정과 승인은 그대로
        controller.explain(3L, new QualityController.ExplanationRequest(9L, "Claude 설명", "llm"));
        assertThat(q.getWorkOrderId()).isEqualTo(9L);
        assertThat(q.getReason()).isEqualTo("Claude 설명");
        assertThat(q.getGenerator()).isEqualTo("llm");
        assertThat(q.getLevel()).isEqualTo(QualityAssessment.Level.HOLD);
        assertThat(q.getStatus()).isEqualTo(QualityAssessment.Status.APPROVED);
    }

    @Test
    void dispositionOnlyAfterApprovedHoldAndOnlyOnce() {
        alarm(true);
        QualityAssessment q = (QualityAssessment) controller.createForAlarm(5L, new QualityController.AssessmentRequest(
                "HOLD", "유화 단계 온도 위험 이탈", "r", "template")).getBody();
        when(repository.findById(6L)).thenReturn(Optional.of(q));
        // 승인 전에는 판정할 수 없다
        assertThat(controller.dispose(6L, new QualityController.DispositionRequest("FAIL", "qa", null)).getStatusCode())
                .isEqualTo(HttpStatus.CONFLICT);
        controller.approve(6L, new QualityController.DecisionRequest("qa-lee", null));
        assertThat(q.isHeld()).isTrue();
        assertThat(controller.dispose(6L, new QualityController.DispositionRequest("MAYBE", "qa", null)).getStatusCode())
                .isEqualTo(HttpStatus.BAD_REQUEST);
        controller.dispose(6L, new QualityController.DispositionRequest("FAIL", "qa-lee", "상 분리 확인"));
        assertThat(q.getDisposition()).isEqualTo(QualityAssessment.Disposition.FAIL);
        assertThat(q.isHeld()).isFalse();
        assertThat(controller.dispose(6L, new QualityController.DispositionRequest("PASS", "qa", null)).getStatusCode())
                .isEqualTo(HttpStatus.CONFLICT);
    }

    @Test
    void explanationRejectsAWorkOrderOfAnotherAlarm() {
        alarm(true);
        QualityAssessment q = QualityAssessment.create(77L, null, "B-1", "EMULSIFYING", "MIXER-01", "temperature",
                QualityAssessment.Level.INSPECT, "b", "r", "template", T0);
        when(repository.findById(4L)).thenReturn(Optional.of(q));
        assertThat(controller.explain(4L, new QualityController.ExplanationRequest(9L, "x", "llm")).getStatusCode())
                .isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
        assertThat(q.getWorkOrderId()).isNull();
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
