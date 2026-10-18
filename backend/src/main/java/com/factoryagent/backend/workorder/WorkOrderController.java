package com.factoryagent.backend.workorder;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.AlarmService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Optional;

@RestController
public class WorkOrderController {

    private static final Logger log = LoggerFactory.getLogger(WorkOrderController.class);

    private final AlarmService alarmService;
    private final WorkOrderRepository repository;

    public WorkOrderController(AlarmService alarmService, WorkOrderRepository repository) {
        this.alarmService = alarmService;
        this.repository = repository;
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
}
