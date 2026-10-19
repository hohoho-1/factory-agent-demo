package com.factoryagent.backend.workorder;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.AlarmService;
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
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

@RestController
public class WorkOrderController {

    private static final Logger log = LoggerFactory.getLogger(WorkOrderController.class);

    private final AlarmService alarmService;
    private final WorkOrderRepository repository;
    private final ApplicationEventPublisher events;

    public WorkOrderController(AlarmService alarmService, WorkOrderRepository repository,
                               ApplicationEventPublisher events) {
        this.alarmService = alarmService;
        this.repository = repository;
        this.events = events;
    }

    /** AI 에이전트가 작성한 조치 지시서를 저장한다. */
    @PostMapping("/api/alarms/{alarmId}/work-orders")
    public ResponseEntity<WorkOrder> create(@PathVariable Long alarmId, @RequestBody WorkOrderRequest req) {
        if (req.title() == null || req.body() == null) {
            return ResponseEntity.badRequest().build();
        }
        Optional<Alarm> alarm = alarmService.findById(alarmId);
        if (alarm.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        WorkOrder saved = repository.save(WorkOrder.of(alarm.get(), req));
        log.info("[WORK ORDER] #{} for alarm #{} ({}): {}", saved.getId(), alarmId, saved.getGenerator(), saved.getTitle());
        events.publishEvent(new WorkOrderCreatedEvent(saved));
        return ResponseEntity.status(HttpStatus.CREATED).body(saved);
    }

    @GetMapping("/api/alarms/{alarmId}/work-orders")
    public List<WorkOrder> byAlarm(@PathVariable Long alarmId) {
        return repository.findByAlarmIdOrderByCreatedAtDesc(alarmId);
    }

    /** 최근 50건. */
    @GetMapping("/api/work-orders")
    public List<WorkOrder> recent() {
        return repository.findTop50ByOrderByCreatedAtDesc();
    }

    /**
     * 과거 유사 조치 이력: 작업자가 조치를 마친 지시서. 에이전트가 새 지시서에 넣는다.
     * 같은 설비·지표 최근 5건, equipmentType 을 주면 같은 유형 다른 설비의 같은 지표 최근 3건을 뒤에 붙인다.
     * 어느 쪽인지는 각 항목의 equipmentId 로 구분한다.
     */
    @GetMapping("/api/work-orders/history")
    public List<WorkOrder> history(@RequestParam String equipmentId, @RequestParam String metric,
                                   @RequestParam(defaultValue = "-1") Long excludeAlarmId,
                                   @RequestParam(required = false) String equipmentType) {
        List<WorkOrder> result = new ArrayList<>(
                repository.findTop5ByEquipmentIdAndMetricAndStatusAndAlarmIdNotOrderByCompletedAtDesc(
                        equipmentId, metric, WorkOrderStatus.COMPLETED, excludeAlarmId));
        if (equipmentType != null && !equipmentType.isBlank()) {
            result.addAll(repository.findTop3ByEquipmentTypeAndEquipmentIdNotAndMetricAndStatusOrderByCompletedAtDesc(
                    equipmentType, equipmentId, metric, WorkOrderStatus.COMPLETED));
        }
        return result;
    }

    /** 작업자가 지시서를 확인했다. */
    @PostMapping("/api/work-orders/{id}/acknowledge")
    public ResponseEntity<WorkOrder> acknowledge(@PathVariable Long id,
                                                 @RequestBody(required = false) AcknowledgeRequest req) {
        Optional<WorkOrder> found = repository.findById(id);
        if (found.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        WorkOrder wo = found.get();
        if (wo.acknowledge(workerOrDefault(req == null ? null : req.worker()), Instant.now())) {
            wo = repository.save(wo);
            log.info("[WORK ORDER] #{} acknowledged by {}", id, wo.getWorker());
            events.publishEvent(new WorkOrderUpdatedEvent(wo));
        }
        return ResponseEntity.ok(wo);
    }

    /**
     * 조치 완료와 결과 입력. 조치 내용과 결과는 필수.
     * 같은 알람의 아직 열린 지시서(경고 단계 지시서 등)는 SUPERSEDED 로 함께 닫는다.
     */
    @Transactional
    @PostMapping("/api/work-orders/{id}/complete")
    public ResponseEntity<WorkOrder> complete(@PathVariable Long id, @RequestBody ActionResultRequest req) {
        if (req.outcome() == null || req.actionTaken() == null || req.actionTaken().isBlank()) {
            return ResponseEntity.badRequest().build();
        }
        Optional<WorkOrder> found = repository.findById(id);
        if (found.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        WorkOrder wo = found.get();
        if (wo.getStatus().isClosed()) {
            return ResponseEntity.status(HttpStatus.CONFLICT).body(wo);
        }
        Instant now = Instant.now();
        String cause = req.rootCause() == null || req.rootCause().isBlank() ? null : req.rootCause().trim();
        // 이름을 비워 보내면 지시서를 확인한 작업자를 그대로 둔다
        String worker = isBlank(req.worker()) && wo.getWorker() != null ? wo.getWorker() : workerOrDefault(req.worker());
        wo.complete(worker, cause, req.actionTaken().trim(), req.outcome(), now);
        wo = repository.save(wo);
        log.info("[WORK ORDER] #{} completed by {} ({}): {}", id, wo.getWorker(), wo.getOutcome(), wo.getActionTaken());
        events.publishEvent(new WorkOrderUpdatedEvent(wo));

        for (WorkOrder sibling : repository.findByAlarmIdOrderByCreatedAtDesc(wo.getAlarmId())) {
            if (!sibling.getId().equals(id) && sibling.supersede(id, now)) {
                repository.save(sibling);
                log.info("[WORK ORDER] #{} superseded by #{}", sibling.getId(), id);
                events.publishEvent(new WorkOrderUpdatedEvent(sibling));
            }
        }
        return ResponseEntity.ok(wo);
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    private static String workerOrDefault(String worker) {
        return isBlank(worker) ? "현장 작업자" : worker.trim();
    }
}
