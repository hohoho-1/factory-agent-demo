package com.factoryagent.backend.control;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.Severity;
import com.factoryagent.backend.alarm.Threshold;
import com.factoryagent.backend.telemetry.SensorReading;
import com.factoryagent.backend.telemetry.SensorReadingRepository;
import com.factoryagent.backend.workorder.WorkOrder;
import com.factoryagent.backend.workorder.WorkOrderRequest;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.http.HttpStatus;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class SetpointServiceTest {

    private static final ControlProperties.SetpointSpec SPEED = new ControlProperties.SetpointSpec(
            "MIXER-01", "speed_sp", "교반 회전수 설정값", "rpm", 40, 66, 15, 60);

    private final SetpointChangeRepository changes = mock(SetpointChangeRepository.class);
    private final SetpointAuditRepository audits = mock(SetpointAuditRepository.class);
    private final SensorReadingRepository readings = mock(SensorReadingRepository.class);
    private final ApplicationEventPublisher events = mock(ApplicationEventPublisher.class);
    private final SetpointService service = new SetpointService(changes, audits, readings,
            new ControlProperties(List.of(SPEED), Duration.ofSeconds(15), Duration.ofSeconds(30)), events);

    SetpointServiceTest() {
        when(changes.save(any(SetpointChange.class))).thenAnswer(inv -> {
            SetpointChange c = inv.getArgument(0);
            if (c.getId() == null) {
                ReflectionTestUtils.setField(c, "id", 7L);
            }
            return c;
        });
    }

    private void currentSpeed(double value, Instant at) {
        when(readings.findFirstByEquipmentIdAndMetricOrderByMeasuredAtDesc("MIXER-01", "speed_sp"))
                .thenReturn(Optional.of(new SensorReading("MIXER-01", "MIXER", "speed_sp", value, "rpm", at, at)));
    }

    private static WorkOrder workOrder() {
        Alarm alarm = Alarm.raise("MIXER-01", "MIXER", "vibration", "mm/s",
                new Threshold.Breach(Severity.WARNING, Threshold.Direction.HIGH, 4.5), 5.0, Instant.now());
        ReflectionTestUtils.setField(alarm, "id", 3L);
        WorkOrder wo = WorkOrder.of(alarm, new WorkOrderRequest("t", "s", "b", "llm", List.of(), List.of(), null));
        ReflectionTestUtils.setField(wo, "id", 11L);
        return wo;
    }

    private SetpointChange proposed(double value) {
        currentSpeed(60, Instant.now());
        return service.propose(workOrder(), new SetpointService.ProposalRequest("speed_sp", value,
                "공진 의심, 회전수 15% 하향", "MAN-MIX-VIB-01 조치 - 경고(WARNING)", "llm"));
    }

    @Test
    void specChecksRangeStepAndCurrentValue() {
        assertThat(SPEED.check(60.0, 51)).isEmpty();
        assertThat(SPEED.check(60.0, 30)).get().asString().contains("운전 범위 40~66rpm");
        assertThat(SPEED.check(60.0, 42)).get().asString().contains("한 번에 15rpm");
        assertThat(SPEED.check(60.0, 60)).get().asString().contains("같은 값");
        assertThat(SPEED.check(null, 51)).get().asString().contains("현재");
    }

    @Test
    void proposeStoresCurrentValueAndAudits() {
        SetpointChange c = proposed(51);

        assertThat(c.getStatus()).isEqualTo(SetpointChange.Status.PROPOSED);
        assertThat(c.getCurrentValue()).isEqualTo(60.0);
        assertThat(c.getWorkOrderId()).isEqualTo(11L);
        assertThat(c.getLabel()).isEqualTo("교반 회전수 설정값");
        ArgumentCaptor<SetpointAudit> audit = ArgumentCaptor.forClass(SetpointAudit.class);
        verify(audits).save(audit.capture());
        assertThat(audit.getValue().getAction()).isEqualTo("PROPOSED");
        assertThat(audit.getValue().getActor()).isEqualTo("AI (llm)");
        verify(events).publishEvent(new SetpointChangeEvent(c));
    }

    @Test
    void proposeRejectsOutOfRangeOrStaleValues() {
        currentSpeed(60, Instant.now());
        assertThatThrownBy(() -> service.propose(workOrder(),
                new SetpointService.ProposalRequest("speed_sp", 90.0, "r", "s", "llm")))
                .isInstanceOf(SetpointException.class)
                .extracting(e -> ((SetpointException) e).getStatus()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);

        currentSpeed(60, Instant.now().minusSeconds(120)); // 게이트웨이가 끊겨 현재값이 오래됨
        assertThatThrownBy(() -> service.propose(workOrder(),
                new SetpointService.ProposalRequest("speed_sp", 51.0, "r", "s", "llm")))
                .hasMessageContaining("읽을 수 없습니다");

        assertThatThrownBy(() -> service.propose(workOrder(),
                new SetpointService.ProposalRequest("vibration", 1.0, "r", "s", "llm")))
                .hasMessageContaining("설정값이 아닙니다");
        verify(changes, never()).save(any());
    }

    @Test
    void approveSendsCommandWithValueBefore() {
        SetpointChange c = proposed(51);
        when(changes.findById(7L)).thenReturn(Optional.of(c));
        currentSpeed(58, Instant.now()); // 그사이 현재값이 바뀌었어도 범위 안이면 승인

        SetpointChange approved = service.approve(7L, "홍길동");

        assertThat(approved.getStatus()).isEqualTo(SetpointChange.Status.SENT);
        assertThat(approved.getDecidedBy()).isEqualTo("홍길동");
        assertThat(approved.getValueBefore()).isEqualTo(58.0);
        assertThat(new SetpointChangeEvent(approved).isCommand()).isTrue();
        assertThatThrownBy(() -> service.approve(7L, "다른 사람"))
                .hasMessageContaining("이미 처리된");
    }

    @Test
    void approveRevalidatesAgainstCurrentValue() {
        SetpointChange c = proposed(51);
        when(changes.findById(7L)).thenReturn(Optional.of(c));
        currentSpeed(51, Instant.now()); // 이미 다른 경로로 51 이 됨

        assertThatThrownBy(() -> service.approve(7L, "홍길동"))
                .isInstanceOf(SetpointException.class)
                .hasMessageContaining("승인할 수 없습니다");
        assertThat(c.getStatus()).isEqualTo(SetpointChange.Status.PROPOSED);
    }

    @Test
    void rejectClosesProposalWithNote() {
        SetpointChange c = proposed(51);
        when(changes.findById(7L)).thenReturn(Optional.of(c));

        SetpointChange rejected = service.reject(7L, "홍길동", " 배치 마감 후 조정 ");

        assertThat(rejected.getStatus()).isEqualTo(SetpointChange.Status.REJECTED);
        assertThat(rejected.getDecisionNote()).isEqualTo("배치 마감 후 조정");
        assertThat(new SetpointChangeEvent(rejected).isCommand()).isFalse();
    }

    @Test
    void resultMarksAppliedOrInterlocked() {
        SetpointChange c = proposed(51);
        when(changes.findById(7L)).thenReturn(Optional.of(c));
        currentSpeed(60, Instant.now());
        service.approve(7L, "홍길동");

        SetpointChange applied = service.onResult(new CommandResult(7L, "MIXER-01", "speed_sp", 51.0, "APPLIED",
                "Good", "PLC 설정값 반영", 60.0, 51.0));

        assertThat(applied.getStatus()).isEqualTo(SetpointChange.Status.APPLIED);
        assertThat(applied.getValueAfter()).isEqualTo(51.0);
        assertThat(applied.getCompletedAt()).isNotNull();

        // 늦게 온 중복 결과는 상태를 바꾸지 않는다
        service.onResult(new CommandResult(7L, "MIXER-01", "speed_sp", 51.0, "INTERLOCKED", "BadOutOfRange", "x",
                60.0, 60.0));
        assertThat(c.getStatus()).isEqualTo(SetpointChange.Status.APPLIED);
    }

    @Test
    void unknownResultIsRecordedAsExternalCommand() {
        SetpointChange c = service.onResult(new CommandResult(null, "MIXER-01", "speed_sp", 95.0, "INTERLOCKED",
                "BadOutOfRange", "허용 범위 30~72rpm 밖입니다", 60.0, 60.0));

        assertThat(c.getOrigin()).isEqualTo(SetpointChange.Origin.EXTERNAL);
        assertThat(c.getStatus()).isEqualTo(SetpointChange.Status.INTERLOCKED);
        assertThat(c.getProposedValue()).isEqualTo(95.0);
        assertThat(c.getResultCode()).isEqualTo("BadOutOfRange");
        assertThat(new SetpointChangeEvent(c).isCommand()).isFalse();
    }

    @Test
    void unansweredCommandsFailAfterTimeout() {
        SetpointChange c = proposed(51);
        when(changes.findById(7L)).thenReturn(Optional.of(c));
        service.approve(7L, "홍길동");
        when(changes.findByStatusAndDecidedAtBefore(any(), any())).thenReturn(List.of(c));

        service.expireUnanswered();

        assertThat(c.getStatus()).isEqualTo(SetpointChange.Status.FAILED);
        assertThat(c.getResultMessage()).contains("응답 없음");
        verify(events, atLeastOnce()).publishEvent(new SetpointChangeEvent(c));
    }
}
