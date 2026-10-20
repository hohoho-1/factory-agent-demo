package com.factoryagent.backend.batch;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 배치 1회의 기록: 레시피, 시작 · 종료, 단계별 소요 시간과 지표 범위. */
@Entity
@Table(name = "batch_run")
public class BatchRun {

    public enum Status { RUNNING, COMPLETED }

    /** 단계 1개의 기록. metrics: 지표 → [최소, 최대] */
    public record PhaseLog(String phase, Instant startedAt, Instant endedAt, Long seconds,
                           Map<String, double[]> metrics) {
    }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "batch_id", nullable = false, length = 32, unique = true)
    private String batchId;

    @Column(name = "equipment_id", nullable = false, length = 32)
    private String equipmentId;

    @Column(length = 100)
    private String recipe;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Status status;

    @Column(name = "started_at", nullable = false)
    private Instant startedAt;

    @Column(name = "ended_at")
    private Instant endedAt;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "phases")
    private List<PhaseLog> phases = new ArrayList<>();

    protected BatchRun() {
    }

    public static BatchRun start(BatchState state) {
        BatchRun r = new BatchRun();
        r.batchId = state.batchId();
        r.equipmentId = state.equipmentId();
        r.recipe = state.recipe();
        r.status = Status.RUNNING;
        r.startedAt = state.phaseStartedAt();
        r.phases = new ArrayList<>(List.of(new PhaseLog(state.phase(), state.phaseStartedAt(), null, null, Map.of())));
        return r;
    }

    /** 지금 단계를 닫고(지표 범위 기록) 다음 단계를 연다. next 가 null 이면 배치 종료. */
    public void advance(String next, Instant at, Map<String, double[]> currentPhaseRange) {
        List<PhaseLog> updated = new ArrayList<>(phases);
        if (!updated.isEmpty()) {
            PhaseLog last = updated.remove(updated.size() - 1);
            updated.add(new PhaseLog(last.phase(), last.startedAt(), at,
                    Duration.between(last.startedAt(), at).toSeconds(), new LinkedHashMap<>(currentPhaseRange)));
        }
        if (next == null) {
            status = Status.COMPLETED;
            endedAt = at;
        } else {
            updated.add(new PhaseLog(next, at, null, null, Map.of()));
        }
        phases = updated;
    }

    public String currentPhase() {
        return phases.isEmpty() ? null : phases.get(phases.size() - 1).phase();
    }

    public Long getId() { return id; }
    public String getBatchId() { return batchId; }
    public String getEquipmentId() { return equipmentId; }
    public String getRecipe() { return recipe; }
    public Status getStatus() { return status; }
    public Instant getStartedAt() { return startedAt; }
    public Instant getEndedAt() { return endedAt; }
    public List<PhaseLog> getPhases() { return phases; }
}
