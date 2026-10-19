package com.factoryagent.backend.handover;

import com.factoryagent.backend.alarm.AlarmRepository;
import com.factoryagent.backend.workorder.WorkOrderRepository;
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
import java.util.List;
import java.util.Optional;

/**
 * 교대 인수인계 리포트.
 * 대시보드: POST 로 요청 → (MQTT) 에이전트: GET context 로 재료를 읽고 POST result 로 채운다 → (SSE) 대시보드에 표시.
 */
@RestController
@RequestMapping("/api/handover-reports")
public class HandoverController {

    private static final Logger log = LoggerFactory.getLogger(HandoverController.class);
    private static final int DEFAULT_HOURS = 8;
    private static final int MAX_HOURS = 24;

    private final HandoverReportRepository reports;
    private final AlarmRepository alarms;
    private final WorkOrderRepository workOrders;
    private final ApplicationEventPublisher events;

    public HandoverController(HandoverReportRepository reports, AlarmRepository alarms,
                              WorkOrderRepository workOrders, ApplicationEventPublisher events) {
        this.reports = reports;
        this.alarms = alarms;
        this.workOrders = workOrders;
        this.events = events;
    }

    public record CreateRequest(Integer hours, String requestedBy) {
    }

    public record ResultRequest(String title, String body, String generator) {
    }

    /** 최근 N시간(기본 8, 최대 24) 인수인계 리포트를 요청한다. 작성은 에이전트가 비동기로 한다. */
    @Transactional
    @PostMapping
    public ResponseEntity<HandoverReport> create(@RequestBody(required = false) CreateRequest req) {
        int hours = req == null || req.hours() == null ? DEFAULT_HOURS : Math.max(1, Math.min(MAX_HOURS, req.hours()));
        Instant to = Instant.now();
        String requestedBy = req == null || req.requestedBy() == null || req.requestedBy().isBlank()
                ? null : req.requestedBy().trim();
        HandoverReport saved = reports.save(HandoverReport.request(to.minus(Duration.ofHours(hours)), to, requestedBy));
        log.info("[HANDOVER] #{} requested for last {}h", saved.getId(), hours);
        events.publishEvent(new HandoverEvent(HandoverEvent.Type.REQUESTED, saved));
        return ResponseEntity.status(HttpStatus.CREATED).body(saved);
    }

    /** 최근 10건. */
    @GetMapping
    public List<HandoverReport> recent() {
        return reports.findTop10ByOrderByCreatedAtDesc();
    }

    @GetMapping("/{id}")
    public ResponseEntity<HandoverReport> get(@PathVariable Long id) {
        return ResponseEntity.of(reports.findById(id));
    }

    /** 에이전트가 읽는 재료: 시간대의 알람·지시서. */
    @Transactional(readOnly = true)
    @GetMapping("/{id}/context")
    public ResponseEntity<HandoverContext> context(@PathVariable Long id) {
        return reports.findById(id).map(r -> ResponseEntity.ok(new HandoverContext(
                r.getWindowFrom(), r.getWindowTo(),
                alarms.findForWindow(r.getWindowFrom(), r.getWindowTo()),
                workOrders.findForWindow(r.getWindowFrom(), r.getWindowTo()).stream()
                        .map(HandoverContext.WorkOrderBrief::of).toList())))
                .orElse(ResponseEntity.notFound().build());
    }

    /** 에이전트가 작성한 리포트를 저장한다. */
    @Transactional
    @PostMapping("/{id}/result")
    public ResponseEntity<HandoverReport> result(@PathVariable Long id, @RequestBody ResultRequest req) {
        if (req.title() == null || req.body() == null) {
            return ResponseEntity.badRequest().build();
        }
        Optional<HandoverReport> found = reports.findById(id);
        if (found.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        HandoverReport report = found.get();
        report.complete(req.title(), req.body(), req.generator() == null ? "unknown" : req.generator(), Instant.now());
        report = reports.save(report);
        log.info("[HANDOVER] #{} written ({}): {}", id, report.getGenerator(), report.getTitle());
        events.publishEvent(new HandoverEvent(HandoverEvent.Type.COMPLETED, report));
        return ResponseEntity.ok(report);
    }
}
