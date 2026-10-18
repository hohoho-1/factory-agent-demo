package com.factoryagent.backend.alarm;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/alarms")
public class AlarmController {

    private final AlarmService alarmService;

    public AlarmController(AlarmService alarmService) {
        this.alarmService = alarmService;
    }

    /** status 미지정: 최근 50건, ACTIVE/CLEARED 지정: 해당 상태 전체. */
    @GetMapping
    public List<Alarm> list(@RequestParam(required = false) AlarmStatus status) {
        return alarmService.find(status);
    }

    @GetMapping("/{id}")
    public ResponseEntity<Alarm> get(@PathVariable Long id) {
        return ResponseEntity.of(alarmService.findById(id));
    }
}
