package com.factoryagent.backend.batch;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.AlarmRepository;
import com.factoryagent.backend.alarm.Severity;
import com.factoryagent.backend.control.SetpointChange;
import com.factoryagent.backend.control.SetpointChangeRepository;
import com.factoryagent.backend.telemetry.ReadingsSavedEvent;
import com.factoryagent.backend.telemetry.SensorReading;
import com.factoryagent.backend.workorder.WorkOrder;
import com.factoryagent.backend.workorder.WorkOrderRepository;
import com.factoryagent.backend.workorder.WorkOrderStatus;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 간이 전자 배치 기록. 배치 단계 이벤트로 배치 시작 · 단계 전환 · 종료를 남기고,
 * 단계마다 측정값의 최소 · 최대를 모아 단계가 끝날 때 함께 저장한다.
 * 기록을 볼 때는 배치 시간대의 알람 · 지시서 · 설정값 변경을 묶어 한 장으로 보여 준다.
 * CGMP 공장은 무인화해도 배치 기록 의무가 그대로라, AI 판단과 사람 승인이 기록에 함께 남아야 한다.
 */
@Service
public class BatchRecordService {

    private static final Logger log = LoggerFactory.getLogger(BatchRecordService.class);

    private final BatchRunRepository runs;
    private final BatchStateTracker tracker;
    private final AlarmRepository alarms;
    private final WorkOrderRepository workOrders;
    private final SetpointChangeRepository setpoints;
    /** 설비 → 지표 → [최소, 최대] (진행 중인 단계) */
    private final Map<String, Map<String, double[]>> ranges = new ConcurrentHashMap<>();

    public BatchRecordService(BatchRunRepository runs, BatchStateTracker tracker, AlarmRepository alarms,
                              WorkOrderRepository workOrders, SetpointChangeRepository setpoints) {
        this.runs = runs;
        this.tracker = tracker;
        this.alarms = alarms;
        this.workOrders = workOrders;
        this.setpoints = setpoints;
    }

    /** 배치 기록 한 장: 배치, 단계, 배치 중 알람과 조치, 설정값 변경, 판정 요약. */
    public record BatchRecord(BatchRun batch, List<Alarm> alarms, List<WorkOrder> workOrders,
                              List<SetpointChange> setpointChanges, Verdict verdict) {
    }

    /**
     * @param level OK(이상 없음) / REVIEW(이상 있었고 조치 완료 → 품질 검토) / HOLD(조치 미완료 → 출하 보류 권고) / RUNNING
     */
    public record Verdict(String level, String text, int alarmCount, int criticalCount, int openActions) {
    }

    @EventListener
    @Transactional
    public void onPhase(BatchPhaseEvent e) {
        BatchState cur = e.current();
        String previousBatch = e.previous() == null ? null : e.previous().batchId();
        Map<String, double[]> range = snapshot(cur.equipmentId());
        if (previousBatch != null && !previousBatch.equals(cur.batchId())) {
            runs.findByBatchId(previousBatch).filter(r -> r.getStatus() == BatchRun.Status.RUNNING).ifPresent(r -> {
                r.advance(null, cur.phaseStartedAt(), range);
                runs.save(r);
                log.info("[BATCH RECORD] {} completed ({} phases)", r.getBatchId(), r.getPhases().size());
            });
        }
        if (cur.batchId() == null) {
            return;
        }
        Optional<BatchRun> existing = runs.findByBatchId(cur.batchId());
        if (existing.isEmpty()) {
            BatchRun run = runs.save(BatchRun.start(cur));
            log.info("[BATCH RECORD] {} started: {} {}", run.getBatchId(), run.getRecipe(), cur.phase());
        } else if (!cur.phase().equals(existing.get().currentPhase())
                && existing.get().getStatus() == BatchRun.Status.RUNNING) {
            BatchRun run = existing.get();
            run.advance(cur.phase(), cur.phaseStartedAt(), cur.batchId().equals(previousBatch) ? range : Map.of());
            runs.save(run);
        }
    }

    /** 진행 중인 배치 단계의 측정값 범위를 모은다. */
    @EventListener
    public void onReadings(ReadingsSavedEvent e) {
        for (SensorReading r : e.readings()) {
            boolean running = tracker.current(r.getEquipmentId()).map(BatchState::running).orElse(false);
            if (!running) {
                continue;
            }
            ranges.computeIfAbsent(r.getEquipmentId(), k -> new ConcurrentHashMap<>())
                    .merge(r.getMetric(), new double[]{r.getValue(), r.getValue()},
                            (a, b) -> new double[]{Math.min(a[0], b[0]), Math.max(a[1], b[1])});
        }
    }

    @Transactional(readOnly = true)
    public List<BatchRun> recent() {
        return runs.findTop20ByOrderByStartedAtDesc();
    }

    @Transactional(readOnly = true)
    public Optional<BatchRecord> record(Long id) {
        return runs.findById(id).map(run -> {
            Instant to = run.getEndedAt() == null ? Instant.now() : run.getEndedAt();
            List<Alarm> during = alarms.findByRaisedAtBetweenOrderByRaisedAt(run.getStartedAt(), to);
            List<WorkOrder> orders = during.isEmpty() ? List.of()
                    : workOrders.findByAlarmIdInOrderByCreatedAt(during.stream().map(Alarm::getId).toList());
            List<SetpointChange> changes = setpoints.findByCreatedAtBetweenOrderByCreatedAt(run.getStartedAt(), to);
            return new BatchRecord(run, during, orders, changes, verdict(run, during, orders));
        });
    }

    static Verdict verdict(BatchRun run, List<Alarm> during, List<WorkOrder> orders) {
        int critical = (int) during.stream().filter(a -> a.getSeverity() == Severity.CRITICAL).count();
        Map<Long, Boolean> handled = new HashMap<>();
        for (WorkOrder w : orders) {
            boolean closed = w.getStatus() == WorkOrderStatus.COMPLETED || w.getStatus() == WorkOrderStatus.SUPERSEDED;
            handled.merge(w.getAlarmId(), closed, Boolean::logicalOr);
        }
        int open = (int) during.stream().filter(a -> !handled.getOrDefault(a.getId(), false)).count();
        if (run.getStatus() == BatchRun.Status.RUNNING) {
            return new Verdict("RUNNING", "배치 진행 중", during.size(), critical, open);
        }
        if (during.isEmpty()) {
            return new Verdict("OK", "배치 중 이상 없음. 품질팀 출하 판정 대기", 0, 0, 0);
        }
        if (open == 0) {
            return new Verdict("REVIEW", "이상 " + during.size() + "건, 조치 완료. 품질팀 검토 후 출하 판정",
                    during.size(), critical, 0);
        }
        return new Verdict("HOLD", "조치가 끝나지 않은 이상 " + open + "건. 출하 보류 권고", during.size(), critical, open);
    }

    private Map<String, double[]> snapshot(String equipmentId) {
        Map<String, double[]> current = ranges.remove(equipmentId);
        return current == null ? Map.of() : new LinkedHashMap<>(current);
    }
}
