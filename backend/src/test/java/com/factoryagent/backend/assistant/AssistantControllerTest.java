package com.factoryagent.backend.assistant;

import com.factoryagent.backend.alarm.AlarmRepository;
import com.factoryagent.backend.workorder.WorkOrderRepository;
import com.factoryagent.backend.workorder.WorkOrderStatus;
import org.junit.jupiter.api.Test;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.http.HttpStatus;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AssistantControllerTest {

    private final AssistantTaskRepository tasks = mock(AssistantTaskRepository.class);
    private final AlarmRepository alarms = mock(AlarmRepository.class);
    private final WorkOrderRepository workOrders = mock(WorkOrderRepository.class);
    private final ApplicationEventPublisher events = mock(ApplicationEventPublisher.class);
    private final AssistantController controller = new AssistantController(tasks, alarms, workOrders, events);

    AssistantControllerTest() {
        when(tasks.save(any(AssistantTask.class))).thenAnswer(inv -> inv.getArgument(0));
    }

    @Test
    void questionIsValidatedAndPublished() {
        assertThat(controller.ask(new AssistantController.QuestionRequest("  ")).getStatusCode())
                .isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(controller.ask(new AssistantController.QuestionRequest("x".repeat(501))).getStatusCode())
                .isEqualTo(HttpStatus.BAD_REQUEST);

        AssistantTask t = controller.ask(new AssistantController.QuestionRequest(" 배합기 진동 원인? ")).getBody();
        assertThat(t.getType()).isEqualTo(AssistantTask.Type.QUESTION);
        assertThat(t.getQuestion()).isEqualTo("배합기 진동 원인?");
        assertThat(t.getStatus()).isEqualTo(AssistantTask.Status.PENDING);
        verify(events).publishEvent(new AssistantEvent(AssistantEvent.Type.REQUESTED, t));
    }

    @Test
    void proposalContextSkipsSameTypeLookupWithoutOwnRecords() {
        AssistantTask t = AssistantTask.manualProposal("MIXER-01", "vibration");
        when(tasks.findById(1L)).thenReturn(Optional.of(t));
        when(workOrders.findTop100ByEquipmentIdAndMetricAndStatusOrderByCompletedAtDesc(
                "MIXER-01", "vibration", WorkOrderStatus.COMPLETED)).thenReturn(List.of());

        AssistantContext ctx = controller.context(1L).getBody();

        assertThat(ctx.workOrders()).isEmpty();
        verify(workOrders, never()).findTop50ByEquipmentTypeAndEquipmentIdNotAndMetricAndStatusOrderByCompletedAtDesc(
                anyString(), anyString(), anyString(), any());
    }

    @Test
    void resultCompletesTask() {
        AssistantTask t = AssistantTask.question("q");
        when(tasks.findById(2L)).thenReturn(Optional.of(t));
        controller.result(2L, new AssistantController.ResultRequest("제목", "본문", "llm"));
        assertThat(t.getStatus()).isEqualTo(AssistantTask.Status.DONE);
        assertThat(t.getGenerator()).isEqualTo("llm");
    }
}
