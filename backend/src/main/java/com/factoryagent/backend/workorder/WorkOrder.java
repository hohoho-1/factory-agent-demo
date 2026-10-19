package com.factoryagent.backend.workorder;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.Severity;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.Instant;
import java.util.List;

/**
 * AI 에이전트가 알람에 대해 작성한 조치 지시서.
 * 알람 시점의 설비·지표·심각도를 함께 남겨 알람이 이후 바뀌어도 당시 판단 근거를 볼 수 있게 한다.
 */
@Entity
@Table(name = "work_order", indexes = {
        @Index(name = "idx_work_order_alarm", columnList = "alarm_id"),
        @Index(name = "idx_work_order_created_at", columnList = "created_at")
})
public class WorkOrder {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "alarm_id", nullable = false)
    private Long alarmId;

    @Column(name = "equipment_id", nullable = false, length = 32)
    private String equipmentId;

    /** 같은 유형의 다른 설비 조치 이력을 찾을 때 쓴다. */
    @Column(name = "equipment_type", nullable = false, length = 32)
    private String equipmentType;

    @Column(nullable = false, length = 32)
    private String metric;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Severity severity;

    @Column(nullable = false, length = 200)
    private String title;

    @Column(length = 500)
    private String summary;

    /** 마크다운 본문. */
    @Column(nullable = false, columnDefinition = "text")
    private String body;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "reference_docs")
    private List<ReferenceDoc> references;

    /** 작업자가 원인을 고를 선택지 (근거 매뉴얼의 '가능 원인'). 이전에 만든 지시서는 null. */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "cause_options")
    private List<String> causeOptions;

    /** 작성 방식: template / llm 등. */
    @Column(nullable = false, length = 32)
    private String generator;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    // ---- 작업자 피드백 ----

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private WorkOrderStatus status;

    @Column(length = 64)
    private String worker;

    @Column(name = "acknowledged_at")
    private Instant acknowledgedAt;

    /** 작업자가 현장에서 확인한 실제 원인. */
    @Column(name = "root_cause", length = 200)
    private String rootCause;

    @Column(name = "action_taken", columnDefinition = "text")
    private String actionTaken;

    @Enumerated(EnumType.STRING)
    @Column(length = 16)
    private ActionOutcome outcome;

    @Column(name = "completed_at")
    private Instant completedAt;

    /** SUPERSEDED 일 때, 대신 조치 완료된 같은 알람의 지시서 id. */
    @Column(name = "superseded_by")
    private Long supersededBy;

    protected WorkOrder() {
    }

    public static WorkOrder of(Alarm alarm, WorkOrderRequest req) {
        WorkOrder w = new WorkOrder();
        w.alarmId = alarm.getId();
        w.equipmentId = alarm.getEquipmentId();
        w.equipmentType = alarm.getEquipmentType();
        w.metric = alarm.getMetric();
        w.severity = alarm.getSeverity();
        w.title = req.title();
        w.summary = req.summary();
        w.body = req.body();
        w.references = req.references() == null ? List.of() : req.references();
        w.causeOptions = req.causeOptions() == null ? List.of() : req.causeOptions();
        w.generator = req.generator() == null ? "unknown" : req.generator();
        w.createdAt = Instant.now();
        w.status = WorkOrderStatus.OPEN;
        return w;
    }

    /** 작업자 확인. 이미 확인·완료된 지시서는 그대로 둔다. */
    public boolean acknowledge(String worker, Instant at) {
        if (getStatus() != WorkOrderStatus.OPEN) {
            return false;
        }
        this.status = WorkOrderStatus.ACKNOWLEDGED;
        this.worker = worker;
        this.acknowledgedAt = at;
        return true;
    }

    /** 조치 완료와 결과 입력. 확인 단계를 건너뛰었으면 확인 시각도 함께 채운다. */
    public void complete(String worker, String rootCause, String actionTaken, ActionOutcome outcome, Instant at) {
        if (acknowledgedAt == null) {
            acknowledgedAt = at;
        }
        this.status = WorkOrderStatus.COMPLETED;
        this.worker = worker;
        this.rootCause = rootCause;
        this.actionTaken = actionTaken;
        this.outcome = outcome;
        this.completedAt = at;
    }

    /** 같은 알람의 다른 지시서가 조치 완료되어 함께 닫는다. 이미 닫힌 지시서는 그대로 둔다. */
    public boolean supersede(Long completedWorkOrderId, Instant at) {
        if (status.isClosed()) {
            return false;
        }
        this.status = WorkOrderStatus.SUPERSEDED;
        this.supersededBy = completedWorkOrderId;
        this.completedAt = at;
        return true;
    }

    public Long getId() { return id; }
    public Long getAlarmId() { return alarmId; }
    public String getEquipmentId() { return equipmentId; }
    public String getEquipmentType() { return equipmentType; }
    public List<String> getCauseOptions() { return causeOptions == null ? List.of() : causeOptions; }
    public String getMetric() { return metric; }
    public Severity getSeverity() { return severity; }
    public String getTitle() { return title; }
    public String getSummary() { return summary; }
    public String getBody() { return body; }
    public List<ReferenceDoc> getReferences() { return references; }
    public String getGenerator() { return generator; }
    public Instant getCreatedAt() { return createdAt; }
    public WorkOrderStatus getStatus() { return status; }
    public String getWorker() { return worker; }
    public Instant getAcknowledgedAt() { return acknowledgedAt; }
    public String getRootCause() { return rootCause; }
    public String getActionTaken() { return actionTaken; }
    public ActionOutcome getOutcome() { return outcome; }
    public Instant getCompletedAt() { return completedAt; }
    public Long getSupersededBy() { return supersededBy; }
}
