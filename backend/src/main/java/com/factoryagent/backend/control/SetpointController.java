package com.factoryagent.backend.control;

import com.factoryagent.backend.workorder.WorkOrder;
import com.factoryagent.backend.workorder.WorkOrderRepository;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 승인형 설정값 제어 API.
 * 에이전트: GET /api/setpoints 로 바꿀 수 있는 설정값·현재값을 읽고, 지시서 저장 뒤 POST …/setpoint-changes 로 제안한다.
 * 대시보드: 제안을 승인(approve)하거나 거절(reject)한다. 결과는 SSE 'setpoint' 이벤트로 온다.
 */
@RestController
public class SetpointController {

    private final SetpointService service;
    private final WorkOrderRepository workOrders;

    public SetpointController(SetpointService service, WorkOrderRepository workOrders) {
        this.service = service;
        this.workOrders = workOrders;
    }

    public record DecisionRequest(String worker, String note) {
    }

    @GetMapping("/api/setpoints")
    public List<SetpointService.SetpointView> setpoints(@RequestParam(required = false) String equipmentId) {
        return service.setpoints(equipmentId);
    }

    /** 최근 30건 (제안 · 승인 · 결과 · 외부 명령). */
    @GetMapping("/api/setpoint-changes")
    public List<SetpointChange> recent() {
        return service.recent();
    }

    @GetMapping("/api/setpoint-changes/{id}/audit")
    public List<SetpointAudit> audit(@PathVariable Long id) {
        return service.audit(id);
    }

    /** AI 에이전트가 지시서와 함께 권장 설정값 변경을 제안한다. 운전 범위를 벗어나면 422. */
    @PostMapping("/api/work-orders/{workOrderId}/setpoint-changes")
    public ResponseEntity<SetpointChange> propose(@PathVariable Long workOrderId,
                                                  @RequestBody SetpointService.ProposalRequest req) {
        WorkOrder wo = workOrders.findById(workOrderId).orElseThrow(() ->
                new SetpointException(HttpStatus.NOT_FOUND, "지시서 WO-" + workOrderId + " 가 없습니다"));
        return ResponseEntity.status(HttpStatus.CREATED).body(service.propose(wo, req));
    }

    @PostMapping("/api/setpoint-changes/{id}/approve")
    public SetpointChange approve(@PathVariable Long id, @RequestBody(required = false) DecisionRequest req) {
        return service.approve(id, worker(req));
    }

    @PostMapping("/api/setpoint-changes/{id}/reject")
    public SetpointChange reject(@PathVariable Long id, @RequestBody(required = false) DecisionRequest req) {
        return service.reject(id, worker(req), req == null ? null : req.note());
    }

    @ExceptionHandler(SetpointException.class)
    public ResponseEntity<Map<String, String>> onError(SetpointException e) {
        return ResponseEntity.status(e.getStatus()).body(Map.of("message", e.getMessage()));
    }

    private static String worker(DecisionRequest req) {
        return req == null || req.worker() == null || req.worker().isBlank() ? "현장 작업자" : req.worker().trim();
    }
}
