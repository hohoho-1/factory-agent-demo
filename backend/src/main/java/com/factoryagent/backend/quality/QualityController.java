package com.factoryagent.backend.quality;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.AlarmRepository;
import com.factoryagent.backend.workorder.WorkOrder;
import com.factoryagent.backend.workorder.WorkOrderRepository;
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

import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 품질 영향 판정 API.
 * 에이전트: 배치 진행 중 알람의 지시서를 저장한 뒤 POST …/quality-assessments 로 판정을 남긴다.
 * 대시보드: HOLD 판정을 품질팀이 승인(approve)하거나 거절(reject)한다. 변경은 SSE 'quality' 이벤트로 온다.
 */
@RestController
public class QualityController {

    private final QualityAssessmentRepository repository;
    private final WorkOrderRepository workOrders;
    private final AlarmRepository alarms;
    private final ApplicationEventPublisher events;
    private final Clock clock;

    public QualityController(QualityAssessmentRepository repository, WorkOrderRepository workOrders,
                             AlarmRepository alarms, ApplicationEventPublisher events, Optional<Clock> clock) {
        this.repository = repository;
        this.workOrders = workOrders;
        this.alarms = alarms;
        this.events = events;
        this.clock = clock.orElse(Clock.systemUTC());
    }

    public record AssessmentRequest(String level, String basis, String reason, String generator) {
    }

    public record DecisionRequest(String worker, String note) {
    }

    /** 최근 50건, 또는 배치 하나의 판정. */
    @GetMapping("/api/quality-assessments")
    public List<QualityAssessment> list(@RequestParam(required = false) String batchId) {
        return batchId == null ? repository.findTop50ByOrderByCreatedAtDesc()
                : repository.findByBatchIdOrderByCreatedAt(batchId);
    }

    @PostMapping("/api/work-orders/{workOrderId}/quality-assessments")
    @Transactional
    public ResponseEntity<?> create(@PathVariable Long workOrderId, @RequestBody AssessmentRequest req) {
        Optional<WorkOrder> wo = workOrders.findById(workOrderId);
        if (wo.isEmpty()) {
            return error(HttpStatus.NOT_FOUND, "지시서 WO-" + workOrderId + " 가 없습니다");
        }
        Optional<Alarm> alarm = alarms.findById(wo.get().getAlarmId());
        if (alarm.isEmpty() || alarm.get().getBatchId() == null) {
            return error(HttpStatus.UNPROCESSABLE_ENTITY, "배치 진행 중 알람이 아니라 품질 판정을 남기지 않습니다");
        }
        QualityAssessment.Level level;
        try {
            level = QualityAssessment.Level.valueOf(req.level());
        } catch (IllegalArgumentException | NullPointerException e) {
            return error(HttpStatus.BAD_REQUEST, "판정은 NO_IMPACT, INSPECT, HOLD 중 하나여야 합니다");
        }
        if (req.basis() == null || req.basis().isBlank()) {
            return error(HttpStatus.BAD_REQUEST, "판정 근거(basis)가 필요합니다");
        }
        Alarm a = alarm.get();
        QualityAssessment saved = repository.save(QualityAssessment.create(a.getId(), workOrderId, a.getBatchId(),
                a.getBatchPhase(), a.getEquipmentId(), a.getMetric(), level, req.basis().trim(),
                req.reason(), req.generator(), Instant.now(clock)));
        events.publishEvent(new QualityAssessmentEvent(saved));
        return ResponseEntity.status(HttpStatus.CREATED).body(saved);
    }

    @PostMapping("/api/quality-assessments/{id}/approve")
    @Transactional
    public ResponseEntity<?> approve(@PathVariable Long id, @RequestBody(required = false) DecisionRequest req) {
        return decide(id, q -> q.approve(worker(req), Instant.now(clock)));
    }

    @PostMapping("/api/quality-assessments/{id}/reject")
    @Transactional
    public ResponseEntity<?> reject(@PathVariable Long id, @RequestBody(required = false) DecisionRequest req) {
        return decide(id, q -> q.reject(worker(req), req == null ? null : req.note(), Instant.now(clock)));
    }

    private ResponseEntity<?> decide(Long id, java.util.function.Consumer<QualityAssessment> action) {
        Optional<QualityAssessment> found = repository.findById(id);
        if (found.isEmpty()) {
            return error(HttpStatus.NOT_FOUND, "품질 판정 #" + id + " 가 없습니다");
        }
        try {
            action.accept(found.get());
        } catch (IllegalStateException e) {
            return error(HttpStatus.CONFLICT, e.getMessage());
        }
        QualityAssessment saved = repository.save(found.get());
        events.publishEvent(new QualityAssessmentEvent(saved));
        return ResponseEntity.ok(saved);
    }

    private static ResponseEntity<Map<String, String>> error(HttpStatus status, String message) {
        return ResponseEntity.status(status).body(Map.of("message", message));
    }

    private static String worker(DecisionRequest req) {
        return req == null || req.worker() == null || req.worker().isBlank() ? "품질팀" : req.worker().trim();
    }
}
