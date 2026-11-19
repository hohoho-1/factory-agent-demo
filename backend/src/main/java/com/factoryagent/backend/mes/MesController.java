package com.factoryagent.backend.mes;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * MES 생산 지시 API.
 * ERP: POST /api/mes/jobs 로 생산 오더를 내려보낸다.
 * 대시보드: 목록을 보고, 작업자가 POST …/start-batch 로 다음 배치를 시작한다.
 */
@RestController
public class MesController {

    private final MesService service;

    public MesController(MesService service) {
        this.service = service;
    }

    /** confirmOutOfOrder: 계획 순서상 앞선 지시를 두고 먼저 시작하는 것을 작업자가 확인했다 */
    public record StartRequest(String worker, Boolean confirmOutOfOrder, String supervisor, String supervisorReason) {
    }

    public record WorkerRequest(String worker) {
    }

    /** 배합기 상태: 마지막 품목, 세정 · 클리어런스 진행. */
    @GetMapping("/api/mes/line")
    public MesService.LineState line() {
        return service.lineState();
    }

    @PostMapping("/api/mes/line/clean")
    public LineChangeover clean(@RequestBody(required = false) WorkerRequest req) {
        return service.startClean(worker(req == null ? null : req.worker()));
    }

    @PostMapping("/api/mes/line/clearance")
    public LineChangeover clearance(@RequestBody(required = false) WorkerRequest req) {
        return service.confirmClearance(worker(req == null ? null : req.worker()));
    }

    private static String worker(String w) {
        return w == null || w.isBlank() ? "현장 작업자" : w.trim();
    }

    @ExceptionHandler(MesRuleException.class)
    public ResponseEntity<Map<String, String>> rule(MesRuleException e) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("code", e.getCode(), "message", e.getMessage()));
    }

    @GetMapping("/api/mes/jobs")
    public List<ProductionJob> jobs() {
        return service.recent();
    }

    @PostMapping("/api/mes/jobs")
    public ResponseEntity<ProductionJob> receive(@RequestBody MesService.JobRequest req) {
        return ResponseEntity.status(HttpStatus.CREATED).body(service.receive(req));
    }

    @PostMapping("/api/mes/jobs/{id}/start-batch")
    public JobBatch startBatch(@PathVariable Long id, @RequestBody(required = false) StartRequest req) {
        String worker = req == null || req.worker() == null || req.worker().isBlank() ? "현장 작업자" : req.worker().trim();
        return service.startNextBatch(id, worker, req != null && Boolean.TRUE.equals(req.confirmOutOfOrder()),
                req == null ? null : req.supervisor(), req == null ? null : req.supervisorReason());
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> badRequest(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("message", e.getMessage()));
    }

    /** 화면은 code 를 보고 작업자에게 확인을 받은 뒤 confirmOutOfOrder=true 로 다시 보낸다. */
    @ExceptionHandler(MesService.OutOfOrderException.class)
    public ResponseEntity<Map<String, String>> outOfOrder(MesService.OutOfOrderException e) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("code", "OUT_OF_ORDER", "message", e.getMessage(),
                "aheadOrderNo", e.getAheadOrderNo()));
    }

    @ExceptionHandler(IllegalStateException.class)
    public ResponseEntity<Map<String, String>> conflict(IllegalStateException e) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("message", e.getMessage()));
    }
}
