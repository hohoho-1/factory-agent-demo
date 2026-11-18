package com.factoryagent.backend.quality;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

/**
 * 배치 진행 중 알람 1건에 대한 품질 영향 판정 (품질 에이전트).
 * HOLD(배치 홀드 · 출하 보류 권고)는 품질팀이 승인해야 확정된다. 나머지는 기록만 남는다.
 */
@Entity
@Table(name = "quality_assessment")
public class QualityAssessment {

    public enum Level { NO_IMPACT, INSPECT, HOLD }

    public enum Status { RECORDED, PENDING, APPROVED, REJECTED }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "alarm_id", nullable = false)
    private Long alarmId;

    @Column(name = "work_order_id", nullable = false)
    private Long workOrderId;

    @Column(name = "batch_id", nullable = false, length = 32)
    private String batchId;

    @Column(name = "batch_phase", length = 32)
    private String batchPhase;

    @Column(name = "equipment_id", nullable = false, length = 32)
    private String equipmentId;

    @Column(nullable = false, length = 32)
    private String metric;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Level level;

    @Column(nullable = false, length = 500)
    private String basis;

    @Column(length = 2000)
    private String reason;

    @Column(length = 32)
    private String generator;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Status status;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "decided_by", length = 64)
    private String decidedBy;

    @Column(name = "decided_at")
    private Instant decidedAt;

    @Column(name = "decision_note", length = 500)
    private String decisionNote;

    protected QualityAssessment() {
    }

    public static QualityAssessment create(Long alarmId, Long workOrderId, String batchId, String batchPhase,
                                           String equipmentId, String metric, Level level, String basis,
                                           String reason, String generator, Instant at) {
        QualityAssessment q = new QualityAssessment();
        q.alarmId = alarmId;
        q.workOrderId = workOrderId;
        q.batchId = batchId;
        q.batchPhase = batchPhase;
        q.equipmentId = equipmentId;
        q.metric = metric;
        q.level = level;
        q.basis = clip(basis, 500);
        q.reason = clip(reason, 2000);
        q.generator = generator;
        q.status = level == Level.HOLD ? Status.PENDING : Status.RECORDED;
        q.createdAt = at;
        return q;
    }

    /** 품질팀이 홀드 권고를 승인한다: 배치 홀드 · 출하 보류가 확정된다. */
    public void approve(String worker, Instant at) {
        decide(Status.APPROVED, worker, null, at);
    }

    /** 품질팀이 홀드 권고를 거절한다 (사유 필수 아님). */
    public void reject(String worker, String note, Instant at) {
        decide(Status.REJECTED, worker, note, at);
    }

    private void decide(Status to, String worker, String note, Instant at) {
        if (status != Status.PENDING) {
            throw new IllegalStateException("승인 대기 중인 판정이 아닙니다 (현재 " + status + ")");
        }
        status = to;
        decidedBy = worker;
        decidedAt = at;
        decisionNote = clip(note, 500);
    }

    private static String clip(String s, int max) {
        return s == null ? null : s.length() <= max ? s : s.substring(0, max);
    }

    public Long getId() { return id; }
    public Long getAlarmId() { return alarmId; }
    public Long getWorkOrderId() { return workOrderId; }
    public String getBatchId() { return batchId; }
    public String getBatchPhase() { return batchPhase; }
    public String getEquipmentId() { return equipmentId; }
    public String getMetric() { return metric; }
    public Level getLevel() { return level; }
    public String getBasis() { return basis; }
    public String getReason() { return reason; }
    public String getGenerator() { return generator; }
    public Status getStatus() { return status; }
    public Instant getCreatedAt() { return createdAt; }
    public String getDecidedBy() { return decidedBy; }
    public Instant getDecidedAt() { return decidedAt; }
    public String getDecisionNote() { return decisionNote; }
}
