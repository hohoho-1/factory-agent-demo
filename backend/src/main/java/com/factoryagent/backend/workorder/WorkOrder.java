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

    /** 작성 방식: template / llm 등. */
    @Column(nullable = false, length = 32)
    private String generator;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected WorkOrder() {
    }

    public static WorkOrder of(Alarm alarm, WorkOrderRequest req) {
        WorkOrder w = new WorkOrder();
        w.alarmId = alarm.getId();
        w.equipmentId = alarm.getEquipmentId();
        w.metric = alarm.getMetric();
        w.severity = alarm.getSeverity();
        w.title = req.title();
        w.summary = req.summary();
        w.body = req.body();
        w.references = req.references() == null ? List.of() : req.references();
        w.generator = req.generator() == null ? "unknown" : req.generator();
        w.createdAt = Instant.now();
        return w;
    }

    public Long getId() { return id; }
    public Long getAlarmId() { return alarmId; }
    public String getEquipmentId() { return equipmentId; }
    public String getMetric() { return metric; }
    public Severity getSeverity() { return severity; }
    public String getTitle() { return title; }
    public String getSummary() { return summary; }
    public String getBody() { return body; }
    public List<ReferenceDoc> getReferences() { return references; }
    public String getGenerator() { return generator; }
    public Instant getCreatedAt() { return createdAt; }
}
