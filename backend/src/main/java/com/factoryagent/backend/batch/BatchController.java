package com.factoryagent.backend.batch;

import com.factoryagent.backend.alarm.AlarmRules;
import com.factoryagent.backend.alarm.Threshold;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
public class BatchController {

    private final BatchStateTracker tracker;
    private final AlarmRules rules;
    private final BatchRecordService records;

    public BatchController(BatchStateTracker tracker, AlarmRules rules, BatchRecordService records) {
        this.tracker = tracker;
        this.rules = rules;
        this.records = records;
    }

    /** 설비별 현재 배치 단계 (가상 PLC 모드에서만 채워진다). */
    @GetMapping("/api/batch/state")
    public List<BatchState> state() {
        return tracker.all();
    }

    /** 설비 유형 → 지표 → 배치 단계 → 임계값. 대시보드가 현재 단계의 기준선을 그릴 때 쓴다. */
    @GetMapping("/api/alarm-rules/phases")
    public Map<String, Map<String, Map<String, Threshold>>> phaseRules() {
        return rules.phaseRules();
    }

    /** 최근 배치 20건. */
    @GetMapping("/api/batches")
    public List<BatchRun> batches() {
        return records.recent();
    }

    /** 배치 기록 한 장: 단계, 배치 중 알람 · 조치 · 설정값 변경, 판정 요약. */
    @GetMapping("/api/batches/{id}/record")
    public ResponseEntity<BatchRecordService.BatchRecord> record(@PathVariable Long id) {
        return ResponseEntity.of(records.record(id));
    }
}
