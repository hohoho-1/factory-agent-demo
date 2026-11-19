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

    public record ExplanationRequest(Long workOrderId, String reason, String generator) {
    }

    /** 지시서가 나온 뒤 품질 판정을 남기는 경로 (판정을 먼저 저장하지 못했을 때의 대체 경로). */
    @PostMapping("/api/work-orders/{workOrderId}/quality-assessments")
    @Transactional
    public ResponseEntity<?> create(@PathVariable Long workOrderId, @RequestBody AssessmentRequest req) {
        Optional<WorkOrder> wo = workOrders.findById(workOrderId);
        if (wo.isEmpty()) {
            return error(HttpStatus.NOT_FOUND, "지시서 WO-" + workOrderId + " 가 없습니다");
        }
        return create(wo.get().getAlarmId(), workOrderId, req);
    }

    /** 급한 판단 먼저: 알람 직후 지시서 없이 규칙 판정부터 남긴다. 홀드면 바로 품질팀 승인 대기가 된다. */
    @PostMapping("/api/alarms/{alarmId}/quality-assessments")
    @Transactional
    public ResponseEntity<?> createForAlarm(@PathVariable Long alarmId, @RequestBody AssessmentRequest req) {
        return create(alarmId, null, req);
    }

    /** 지시서가 나오면 판정에 지시서를 연결하고 이유 설명을 바꾼다. 판정과 품질팀 결정은 그대로다. */
    @PostMapping("/api/quality-assessments/{id}/explanation")
    @Transactional
    public ResponseEntity<?> explain(@PathVariable Long id, @RequestBody ExplanationRequest req) {
        Optional<QualityAssessment> found = repository.findById(id);
        if (found.isEmpty()) {
            return error(HttpStatus.NOT_FOUND, "품질 판정 #" + id + " 가 없습니다");
        }
        QualityAssessment q = found.get();
        if (req.workOrderId() != null) {
            Optional<WorkOrder> wo = workOrders.findById(req.workOrderId());
            if (wo.isEmpty() || !wo.get().getAlarmId().equals(q.getAlarmId())) {
                return error(HttpStatus.UNPROCESSABLE_ENTITY, "같은 알람의 지시서가 아닙니다");
            }
        }
        q.explain(req.workOrderId(), req.reason(), req.generator());
        QualityAssessment saved = repository.save(q);
        events.publishEvent(new QualityAssessmentEvent(saved));
        return ResponseEntity.ok(saved);
    }

    private ResponseEntity<?> create(Long alarmId, Long workOrderId, AssessmentRequest req) {
        Optional<Alarm> alarm = alarms.findById(alarmId);
        if (alarm.isEmpty()) {
            return error(HttpStatus.NOT_FOUND, "알람 #" + alarmId + " 가 없습니다");
        }
        if (alarm.get().getBatchId() == null) {
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

    public record DispositionRequest(String result, String worker, String note) {
    }

    /**
     * 홀드 배치의 검사 판정: PASS(합격 → 보류 해제) / FAIL(불합격 → 폐기). 판정은 ERP 에 알려져
     * 보류 재고가 가용 재고로 바뀌거나 폐기되고, 불합격이면 ERP 가 재생산 오더를 계획한다.
     */
    @PostMapping("/api/quality-assessments/{id}/disposition")
    @Transactional
    public ResponseEntity<?> dispose(@PathVariable Long id, @RequestBody DispositionRequest req) {
        QualityAssessment.Disposition result;
        try {
            result = QualityAssessment.Disposition.valueOf(req.result());
        } catch (IllegalArgumentException | NullPointerException e) {
            return error(HttpStatus.BAD_REQUEST, "판정은 PASS 또는 FAIL 이어야 합니다");
        }
        String worker = req.worker() == null || req.worker().isBlank() ? "품질팀" : req.worker().trim();
        return decide(id, q -> q.dispose(result, worker, req.note(), Instant.now(clock)));
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
