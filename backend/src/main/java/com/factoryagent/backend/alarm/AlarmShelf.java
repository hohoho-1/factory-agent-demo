package com.factoryagent.backend.alarm;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

/**
 * 알람 일시 억제(shelving, ISA-18.2). 정비 중인 설비처럼 알람이 나도 의미가 없을 때
 * 작업자가 사유와 함께 정해진 시간 동안 새 알람을 끈다. 시간이 지나면 저절로 풀린다.
 * metric 이 null 이면 그 설비의 모든 지표.
 */
@Entity
@Table(name = "alarm_shelf")
public class AlarmShelf {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "equipment_id", nullable = false, length = 32)
    private String equipmentId;

    @Column(length = 32)
    private String metric;

    @Column(nullable = false, length = 200)
    private String reason;

    @Column(name = "shelved_by", nullable = false, length = 64)
    private String shelvedBy;

    @Column(name = "shelved_at", nullable = false)
    private Instant shelvedAt;

    @Column(name = "until_at", nullable = false)
    private Instant untilAt;

    @Column(name = "released_by", length = 64)
    private String releasedBy;

    @Column(name = "released_at")
    private Instant releasedAt;

    protected AlarmShelf() {
    }

    public static AlarmShelf shelve(String equipmentId, String metric, String reason, String worker,
                                    Instant at, Instant until) {
        AlarmShelf s = new AlarmShelf();
        s.equipmentId = equipmentId;
        s.metric = metric;
        s.reason = reason.length() <= 200 ? reason : reason.substring(0, 200);
        s.shelvedBy = worker;
        s.shelvedAt = at;
        s.untilAt = until;
        return s;
    }

    /** 이 시각에 이 설비·지표의 알람을 억제하는지. */
    public boolean covers(String equipmentId, String metric, Instant at) {
        return releasedAt == null && at.isBefore(untilAt) && this.equipmentId.equals(equipmentId)
                && (this.metric == null || this.metric.equals(metric));
    }

    public boolean isActive(Instant at) {
        return releasedAt == null && at.isBefore(untilAt);
    }

    public void release(String worker, Instant at) {
        this.releasedBy = worker;
        this.releasedAt = at;
    }

    public Long getId() { return id; }
    public String getEquipmentId() { return equipmentId; }
    public String getMetric() { return metric; }
    public String getReason() { return reason; }
    public String getShelvedBy() { return shelvedBy; }
    public Instant getShelvedAt() { return shelvedAt; }
    public Instant getUntilAt() { return untilAt; }
    public String getReleasedBy() { return releasedBy; }
    public Instant getReleasedAt() { return releasedAt; }
}
