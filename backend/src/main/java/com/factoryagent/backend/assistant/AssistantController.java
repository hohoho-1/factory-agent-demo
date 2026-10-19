package com.factoryagent.backend.assistant;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.AlarmRepository;
import com.factoryagent.backend.handover.HandoverContext.WorkOrderBrief;
import com.factoryagent.backend.workorder.WorkOrder;
import com.factoryagent.backend.workorder.WorkOrderRepository;
import com.factoryagent.backend.workorder.WorkOrderStatus;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * AI 작업: 자연어 질의, 매뉴얼 개선 제안.
 * 대시보드: POST 로 요청 → (MQTT) 에이전트: GET context 로 재료를 읽고 POST result 로 채운다 → (SSE) 대시보드에 표시.
 */
@RestController
@RequestMapping("/api/assistant")
public class AssistantController {

    private static final Logger log = LoggerFactory.getLogger(AssistantController.class);
    private static final int MAX_QUESTION = 500;
    private static final Duration QUESTION_LOOKBACK = Duration.ofDays(7);

    private final AssistantTaskRepository tasks;
    private final AlarmRepository alarms;
    private final WorkOrderRepository workOrders;
    private final ApplicationEventPublisher events;

    public AssistantController(AssistantTaskRepository tasks, AlarmRepository alarms,
                               WorkOrderRepository workOrders, ApplicationEventPublisher events) {
        this.tasks = tasks;
        this.alarms = alarms;
        this.workOrders = workOrders;
        this.events = events;
    }

    public record QuestionRequest(String question) {
    }

    public record ProposalRequest(String equipmentId, String metric) {
    }

    public record ResultRequest(String title, String body, String generator) {
    }

    /** 작업자의 자연어 질문. 최근 7일 알람·조치 이력과 매뉴얼을 근거로 에이전트가 답한다. */
    @Transactional
    @PostMapping("/questions")
    public ResponseEntity<AssistantTask> ask(@RequestBody QuestionRequest req) {
        String q = req.question() == null ? "" : req.question().trim();
        if (q.isEmpty() || q.length() > MAX_QUESTION) {
            return ResponseEntity.badRequest().build();
        }
        return created(tasks.save(AssistantTask.question(q)));
    }

    /** 설비·지표의 조치 이력으로 매뉴얼 개선안을 요청한다. */
    @Transactional
    @PostMapping("/manual-proposals")
    public ResponseEntity<AssistantTask> propose(@RequestBody ProposalRequest req) {
        if (req.equipmentId() == null || req.equipmentId().isBlank() || req.metric() == null || req.metric().isBlank()) {
            return ResponseEntity.badRequest().build();
        }
        return created(tasks.save(AssistantTask.manualProposal(req.equipmentId().trim(), req.metric().trim())));
    }

    private ResponseEntity<AssistantTask> created(AssistantTask task) {
        log.info("[ASSISTANT] #{} {} requested", task.getId(), task.getType());
        events.publishEvent(new AssistantEvent(AssistantEvent.Type.REQUESTED, task));
        return ResponseEntity.status(HttpStatus.CREATED).body(task);
    }

    /** 최근 20건. */
    @GetMapping("/tasks")
    public List<AssistantTask> recent() {
        return tasks.findTop20ByOrderByCreatedAtDesc();
    }

    @GetMapping("/tasks/{id}")
    public ResponseEntity<AssistantTask> get(@PathVariable Long id) {
        return ResponseEntity.of(tasks.findById(id));
    }

    /** 에이전트가 읽는 재료. */
    @Transactional(readOnly = true)
    @GetMapping("/tasks/{id}/context")
    public ResponseEntity<AssistantContext> context(@PathVariable Long id) {
        Optional<AssistantTask> found = tasks.findById(id);
        if (found.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        AssistantTask task = found.get();
        if (task.getType() == AssistantTask.Type.QUESTION) {
            Instant since = task.getCreatedAt().minus(QUESTION_LOOKBACK);
            return ResponseEntity.ok(new AssistantContext(task,
                    alarms.findTop200ByRaisedAtAfterOrderByRaisedAtDesc(since),
                    briefs(workOrders.findTop200ByCreatedAtAfterOrderByCreatedAtDesc(since))));
        }

        List<Alarm> history = alarms.findTop100ByEquipmentIdAndMetricOrderByRaisedAtDesc(
                task.getEquipmentId(), task.getMetric());
        List<WorkOrder> done = new ArrayList<>(workOrders.findTop100ByEquipmentIdAndMetricAndStatusOrderByCompletedAtDesc(
                task.getEquipmentId(), task.getMetric(), WorkOrderStatus.COMPLETED));
        if (!done.isEmpty()) {
            done.addAll(workOrders.findTop50ByEquipmentTypeAndEquipmentIdNotAndMetricAndStatusOrderByCompletedAtDesc(
                    done.get(0).getEquipmentType(), task.getEquipmentId(), task.getMetric(), WorkOrderStatus.COMPLETED));
        }
        return ResponseEntity.ok(new AssistantContext(task, history, briefs(done)));
    }

    /** 에이전트가 작성한 결과를 저장한다. */
    @Transactional
    @PostMapping("/tasks/{id}/result")
    public ResponseEntity<AssistantTask> result(@PathVariable Long id, @RequestBody ResultRequest req) {
        if (req.title() == null || req.body() == null) {
            return ResponseEntity.badRequest().build();
        }
        Optional<AssistantTask> found = tasks.findById(id);
        if (found.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        AssistantTask task = found.get();
        task.complete(req.title(), req.body(), req.generator() == null ? "unknown" : req.generator(), Instant.now());
        task = tasks.save(task);
        log.info("[ASSISTANT] #{} {} written ({}): {}", id, task.getType(), task.getGenerator(), task.getTitle());
        events.publishEvent(new AssistantEvent(AssistantEvent.Type.COMPLETED, task));
        return ResponseEntity.ok(task);
    }

    private static List<WorkOrderBrief> briefs(List<WorkOrder> list) {
        return list.stream().map(WorkOrderBrief::of).toList();
    }
}
