package com.factoryagent.backend.alarm;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;

import java.time.Instant;

/**
 * 알람 1건. 같은 설비·지표에는 ACTIVE 알람이 최대 1개이며,
 * 이상이 지속되는 동안 심각도 상승(escalate)·최악값(peak)이 이 행에 누적되고
 * 정상 복귀 시 CLEARED 로 닫힌다.
 */
@Entity
@Table(name = "alarm", indexes = {
        @Index(name = "idx_alarm_eq_metric_status", columnList = "equipment_id, metric, status"),
        @Index(name = "idx_alarm_raised_at", columnList = "raised_at")
})
public class Alarm {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "equipment_id", nullable = false, length = 32)
    private String equipmentId;

    @Column(name = "equipment_type", nullable = false, length = 32)
    private String equipmentType;

    @Column(nullable = false, length = 32)
    private String metric;

    @Column(length = 16)
    private String unit;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Severity severity;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private AlarmStatus status;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 8)
    private Threshold.Direction direction;

    /** 현재 심각도를 판정한 경계값. */
    @Column(name = "threshold_value", nullable = false)
    private double thresholdValue;

    @Column(name = "trigger_value", nullable = false)
    private double triggerValue;

    @Column(name = "peak_value", nullable = false)
    private double peakValue;

    @Column(name = "last_value", nullable = false)
    private double lastValue;

    @Column(nullable = false, length = 255)
    private String message;

    @Column(name = "raised_at", nullable = false)
    private Instant raisedAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @Column(name = "cleared_at")
    private Instant clearedAt;

    /** 추세 예측 경보가 이 알람보다 몇 초 먼저였는지. 예측 없이 발생했으면 null. */
    @Column(name = "forecast_lead_seconds")
    private Long forecastLeadSeconds;

    /** 발생 시점의 배치 단계 (예: EMULSIFYING). 단계를 모르면 null. 같은 값이라도 단계마다 정상 범위가 다르다 */
    @Column(name = "batch_phase", length = 32)
    private String batchPhase;

    @Column(name = "batch_id", length = 32)
    private String batchId;

    protected Alarm() {
    }

    public Alarm inBatch(String phase, String batchId) {
        this.batchPhase = phase;
        this.batchId = batchId;
        return this;
    }

    public void markForecast(long leadSeconds) {
        this.forecastLeadSeconds = leadSeconds;
    }

    public static Alarm raise(String equipmentId, String equipmentType, String metric, String unit,
                              Threshold.Breach breach, double value, Instant at) {
        Alarm a = new Alarm();
        a.equipmentId = equipmentId;
        a.equipmentType = equipmentType;
        a.metric = metric;
        a.unit = unit;
        a.status = AlarmStatus.ACTIVE;
        a.direction = breach.direction();
        a.triggerValue = value;
        a.peakValue = value;
        a.lastValue = value;
        a.raisedAt = at;
        a.updatedAt = at;
        a.applyBreach(breach, value);
        return a;
    }

    /** 더 높은 심각도로 올린다. 같거나 낮은 심각도면 무시. */
    public boolean escalate(Threshold.Breach breach, double value, Instant at) {
        if (breach.severity().compareTo(severity) <= 0) {
            return false;
        }
        applyBreach(breach, value);
        updatedAt = at;
        return true;
    }

    /** 활성 알람 동안 들어오는 측정값을 반영한다. */
    public void track(double value, Instant at) {
        lastValue = value;
        boolean worse = direction == Threshold.Direction.HIGH ? value > peakValue : value < peakValue;
        if (worse) {
            peakValue = value;
        }
        updatedAt = at;
    }

    public void clear(Instant at) {
        status = AlarmStatus.CLEARED;
        clearedAt = at;
        updatedAt = at;
    }

    private void applyBreach(Threshold.Breach breach, double value) {
        severity = breach.severity();
        thresholdValue = breach.limit();
        message = String.format("%s %s %.2f%s %s %.2f (%s)",
                equipmentId, metric, value, unit == null ? "" : unit,
                breach.operator(), breach.limit(), breach.severity());
    }

    public Long getId() { return id; }
    public String getEquipmentId() { return equipmentId; }
    public String getEquipmentType() { return equipmentType; }
    public String getMetric() { return metric; }
    public String getUnit() { return unit; }
    public Severity getSeverity() { return severity; }
    public AlarmStatus getStatus() { return status; }
    public Threshold.Direction getDirection() { return direction; }
    public double getThresholdValue() { return thresholdValue; }
    public double getTriggerValue() { return triggerValue; }
    public double getPeakValue() { return peakValue; }
    public double getLastValue() { return lastValue; }
    public String getMessage() { return message; }
    public Instant getRaisedAt() { return raisedAt; }
    public Instant getUpdatedAt() { return updatedAt; }
    public Instant getClearedAt() { return clearedAt; }
    public Long getForecastLeadSeconds() { return forecastLeadSeconds; }
    public String getBatchPhase() { return batchPhase; }
    public String getBatchId() { return batchId; }
}
