package com.factoryagent.backend.handover;

import com.factoryagent.backend.alarm.AlarmRepository;
import com.factoryagent.backend.workorder.WorkOrderRepository;
import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.http.HttpStatus;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class HandoverControllerTest {

    private final HandoverReportRepository reports = mock(HandoverReportRepository.class);
    private final AlarmRepository alarms = mock(AlarmRepository.class);
    private final WorkOrderRepository workOrders = mock(WorkOrderRepository.class);
    private final ApplicationEventPublisher events = mock(ApplicationEventPublisher.class);
    private final HandoverController controller = new HandoverController(reports, alarms, workOrders, events);

    HandoverControllerTest() {
        when(reports.save(any(HandoverReport.class))).thenAnswer(inv -> inv.getArgument(0));
    }

    @Test
    void createClampsHoursAndPublishesRequest() {
        HandoverReport r = controller.create(new HandoverController.CreateRequest(100, " ")).getBody();
        assertThat(r.getStatus()).isEqualTo(HandoverReport.Status.PENDING);
        assertThat(Duration.between(r.getWindowFrom(), r.getWindowTo())).isEqualTo(Duration.ofHours(24));
        assertThat(r.getRequestedBy()).isNull();
        verify(events).publishEvent(new HandoverEvent(HandoverEvent.Type.REQUESTED, r));

        HandoverReport defaults = controller.create(null).getBody();
        assertThat(Duration.between(defaults.getWindowFrom(), defaults.getWindowTo())).isEqualTo(Duration.ofHours(8));
    }

    @Test
    void contextUsesReportWindow() {
        Instant to = Instant.parse("2026-10-19T10:00:00Z");
        HandoverReport r = HandoverReport.request(to.minus(Duration.ofHours(8)), to, null);
        when(reports.findById(5L)).thenReturn(Optional.of(r));
        when(alarms.findForWindow(r.getWindowFrom(), to)).thenReturn(List.of());
        when(workOrders.findForWindow(r.getWindowFrom(), to)).thenReturn(List.of());

        HandoverContext ctx = controller.context(5L).getBody();
        assertThat(ctx.from()).isEqualTo(r.getWindowFrom());
        assertThat(ctx.to()).isEqualTo(to);
        assertThat(controller.context(6L).getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
    }

    @Test
    void resultCompletesReport() {
        HandoverReport r = HandoverReport.request(Instant.now().minusSeconds(3600), Instant.now(), null);
        when(reports.findById(5L)).thenReturn(Optional.of(r));

        controller.result(5L, new HandoverController.ResultRequest("제목", "본문", "llm"));

        assertThat(r.getStatus()).isEqualTo(HandoverReport.Status.DONE);
        assertThat(r.getGenerator()).isEqualTo("llm");
        assertThat(r.getCompletedAt()).isNotNull();
        assertThat(controller.result(5L, new HandoverController.ResultRequest(null, "본문", "llm")).getStatusCode())
                .isEqualTo(HttpStatus.BAD_REQUEST);
    }
}
