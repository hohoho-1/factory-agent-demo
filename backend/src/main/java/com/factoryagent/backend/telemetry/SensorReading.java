package com.factoryagent.backend.telemetry;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Table;

import java.time.Instant;

/**
 * 센서 측정값 1건 (설비 1대 × 지표 1개 × 시각 1개).
 * MQTT 메시지 1개(설비 단위)는 지표 수만큼의 행으로 펼쳐서 저장한다.
 */
@Entity
@Table(name = "sensor_reading", indexes = {
        @Index(name = "idx_reading_eq_metric_time", columnList = "equipment_id, metric, measured_at")
})
public class SensorReading {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "equipment_id", nullable = false, length = 32)
    private String equipmentId;

    @Column(name = "equipment_type", nullable = false, length = 32)
    private String equipmentType;

    @Column(nullable = false, length = 32)
    private String metric;

    @Column(nullable = false)
    private double value;

    @Column(length = 16)
    private String unit;

    @Column(name = "measured_at", nullable = false)
    private Instant measuredAt;

    @Column(name = "received_at", nullable = false)
    private Instant receivedAt;

    protected SensorReading() {
    }

    public SensorReading(String equipmentId, String equipmentType, String metric, double value,
                         String unit, Instant measuredAt, Instant receivedAt) {
        this.equipmentId = equipmentId;
        this.equipmentType = equipmentType;
        this.metric = metric;
        this.value = value;
        this.unit = unit;
        this.measuredAt = measuredAt;
        this.receivedAt = receivedAt;
    }

    public Long getId() { return id; }
    public String getEquipmentId() { return equipmentId; }
    public String getEquipmentType() { return equipmentType; }
    public String getMetric() { return metric; }
    public double getValue() { return value; }
    public String getUnit() { return unit; }
    public Instant getMeasuredAt() { return measuredAt; }
    public Instant getReceivedAt() { return receivedAt; }
}
