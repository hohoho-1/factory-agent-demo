package com.factoryagent.backend.alarm;

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

/** 알람 일시 억제: 시작(사유 필수, 최대 120분) · 해제 · 진행 중 목록. */
@RestController
public class AlarmShelfController {

    private final AlarmShelfService service;

    public AlarmShelfController(AlarmShelfService service) {
        this.service = service;
    }

    public record ReleaseRequest(String worker) {
    }

    @GetMapping("/api/alarm-shelves")
    public List<AlarmShelf> active() {
        return service.active();
    }

    @PostMapping("/api/alarm-shelves")
    public ResponseEntity<AlarmShelf> shelve(@RequestBody AlarmShelfService.ShelveRequest req) {
        return ResponseEntity.status(HttpStatus.CREATED).body(service.shelve(req));
    }

    @PostMapping("/api/alarm-shelves/{id}/release")
    public ResponseEntity<AlarmShelf> release(@PathVariable Long id, @RequestBody(required = false) ReleaseRequest req) {
        return ResponseEntity.of(service.release(id, req == null ? null : req.worker()));
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> onBadRequest(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("message", e.getMessage()));
    }
}
