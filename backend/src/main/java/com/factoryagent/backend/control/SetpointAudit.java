package com.factoryagent.backend.control;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

/** 설정값 변경 감사 기록 1줄. 덧붙이기만 하고 고치지 않는다. action 은 바뀐 뒤 상태 이름(PROPOSED, APPROVED …). */
@Entity
@Table(name = "setpoint_audit")
public class SetpointAudit {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "change_id", nullable = false)
    private Long changeId;

    @Column(nullable = false, length = 16)
    private String action;

    @Column(nullable = false, length = 64)
    private String actor;

    @Column(name = "value_before")
    private Double valueBefore;

    @Column(name = "value_after")
    private Double valueAfter;

    @Column(length = 500)
    private String message;

    @Column(nullable = false)
    private Instant at;

    protected SetpointAudit() {
    }

    public static SetpointAudit of(SetpointChange change, String action, String actor,
                                   Double before, Double after, String message, Instant at) {
        SetpointAudit a = new SetpointAudit();
        a.changeId = change.getId();
        a.action = action;
        a.actor = actor;
        a.valueBefore = before;
        a.valueAfter = after;
        a.message = message == null || message.length() <= 500 ? message : message.substring(0, 500);
        a.at = at;
        return a;
    }

    public Long getId() { return id; }
    public Long getChangeId() { return changeId; }
    public String getAction() { return action; }
    public String getActor() { return actor; }
    public Double getValueBefore() { return valueBefore; }
    public Double getValueAfter() { return valueAfter; }
    public String getMessage() { return message; }
    public Instant getAt() { return at; }
}
