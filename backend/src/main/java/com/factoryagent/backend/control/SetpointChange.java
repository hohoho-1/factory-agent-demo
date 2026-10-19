package com.factoryagent.backend.control;

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
 * 설정값 변경 1건. AI 가 지시서와 함께 제안하고(PROPOSED), 작업자가 승인하면 명령을 내려보낸다(SENT).
 * 게이트웨이가 PLC 에 쓴 결과로 APPLIED(반영) / INTERLOCKED(PLC 인터록 거부) / FAILED(응답 없음)가 된다.
 * 게이트웨이로 직접 들어온 명령(백엔드 승인 없음)도 결과를 EXTERNAL 로 남긴다.
 */
@Entity
@Table(name = "setpoint_change")
public class SetpointChange {

    public enum Origin { AI, EXTERNAL }

    public enum Status {
        PROPOSED, REJECTED, SENT, APPLIED, INTERLOCKED, FAILED;

        public boolean isFinal() {
            return this != PROPOSED && this != SENT;
        }
    }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Origin origin;

    @Column(name = "work_order_id")
    private Long workOrderId;

    @Column(name = "alarm_id")
    private Long alarmId;

    @Column(name = "equipment_id", nullable = false, length = 32)
    private String equipmentId;

    @Column(nullable = false, length = 64)
    private String tag;

    @Column(length = 100)
    private String label;

    @Column(length = 16)
    private String unit;

    /** 제안 시점의 현재값. */
    @Column(name = "current_value")
    private Double currentValue;

    @Column(name = "proposed_value", nullable = false)
    private double proposedValue;

    @Column(length = 1000)
    private String reason;

    /** 근거 표시 (예: "MAN-MIX-VIB-01 조치 - 경고(WARNING)"). */
    @Column(length = 500)
    private String sources;

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

    /** 승인 시점(또는 PLC 가 보고한) 변경 전 값. */
    @Column(name = "value_before")
    private Double valueBefore;

    /** PLC 가 보고한 변경 후 값 (거부되면 그대로인 값). */
    @Column(name = "value_after")
    private Double valueAfter;

    @Column(name = "result_code", length = 64)
    private String resultCode;

    @Column(name = "result_message", length = 500)
    private String resultMessage;

    @Column(name = "completed_at")
    private Instant completedAt;

    protected SetpointChange() {
    }

    public static SetpointChange propose(Long workOrderId, Long alarmId, ControlProperties.SetpointSpec spec,
                                         Double currentValue, double proposedValue, String reason, String sources,
                                         String generator, Instant at) {
        SetpointChange c = base(Origin.AI, spec.equipmentId(), spec.tag(), proposedValue, at);
        c.workOrderId = workOrderId;
        c.alarmId = alarmId;
        c.label = spec.label();
        c.unit = spec.unit();
        c.currentValue = currentValue;
        c.reason = truncate(reason, 1000);
        c.sources = truncate(sources, 500);
        c.generator = generator;
        c.status = Status.PROPOSED;
        return c;
    }

    /** 백엔드를 거치지 않고 게이트웨이로 들어온 명령의 결과. */
    public static SetpointChange external(String equipmentId, String tag, String label, String unit,
                                          double requested, Instant at) {
        SetpointChange c = base(Origin.EXTERNAL, equipmentId, tag, requested, at);
        c.label = label;
        c.unit = unit;
        c.status = Status.SENT;
        c.decidedBy = "외부 명령";
        return c;
    }

    private static SetpointChange base(Origin origin, String equipmentId, String tag, double value, Instant at) {
        SetpointChange c = new SetpointChange();
        c.origin = origin;
        c.equipmentId = equipmentId;
        c.tag = tag;
        c.proposedValue = value;
        c.createdAt = at;
        return c;
    }

    public void approve(String worker, double valueBefore, Instant at) {
        requireStatus(Status.PROPOSED);
        this.status = Status.SENT;
        this.decidedBy = worker;
        this.decidedAt = at;
        this.valueBefore = valueBefore;
    }

    public void reject(String worker, String note, Instant at) {
        requireStatus(Status.PROPOSED);
        this.status = Status.REJECTED;
        this.decidedBy = worker;
        this.decidedAt = at;
        this.decisionNote = truncate(note, 500);
        this.completedAt = at;
    }

    /** PLC(게이트웨이)가 보고한 결과. */
    public void complete(Status result, Double before, Double after, String code, String message, Instant at) {
        requireStatus(Status.SENT);
        if (!result.isFinal() || result == Status.REJECTED) {
            throw new IllegalArgumentException("not a command result: " + result);
        }
        this.status = result;
        if (before != null) {
            this.valueBefore = before;
        }
        this.valueAfter = after;
        this.resultCode = code;
        this.resultMessage = truncate(message, 500);
        this.completedAt = at;
    }

    private void requireStatus(Status expected) {
        if (status != expected) {
            throw new IllegalStateException("setpoint change #" + id + " is " + status + ", expected " + expected);
        }
    }

    private static String truncate(String s, int max) {
        return s == null || s.length() <= max ? s : s.substring(0, max);
    }

    public Long getId() { return id; }
    public Origin getOrigin() { return origin; }
    public Long getWorkOrderId() { return workOrderId; }
    public Long getAlarmId() { return alarmId; }
    public String getEquipmentId() { return equipmentId; }
    public String getTag() { return tag; }
    public String getLabel() { return label; }
    public String getUnit() { return unit; }
    public Double getCurrentValue() { return currentValue; }
    public double getProposedValue() { return proposedValue; }
    public String getReason() { return reason; }
    public String getSources() { return sources; }
    public String getGenerator() { return generator; }
    public Status getStatus() { return status; }
    public Instant getCreatedAt() { return createdAt; }
    public String getDecidedBy() { return decidedBy; }
    public Instant getDecidedAt() { return decidedAt; }
    public String getDecisionNote() { return decisionNote; }
    public Double getValueBefore() { return valueBefore; }
    public Double getValueAfter() { return valueAfter; }
    public String getResultCode() { return resultCode; }
    public String getResultMessage() { return resultMessage; }
    public Instant getCompletedAt() { return completedAt; }
}
