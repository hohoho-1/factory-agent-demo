package com.factoryagent.backend.mes;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

/** 제품 전환 1회: 배합기 세정(CIP) → 세정 완료 → 라인 클리어런스 확인. 누가 언제 했는지 기록으로 남는다. */
@Entity
@Table(name = "line_changeover")
public class LineChangeover {

    public enum Status { CLEANING, CLEANED, CLEARED, FAILED }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "equipment_id", nullable = false, length = 32)
    private String equipmentId;

    @Column(name = "cip_id", nullable = false, unique = true, length = 32)
    private String cipId;

    @Column(name = "from_item_code", length = 32)
    private String fromItemCode;

    @Column(name = "from_item_name", length = 100)
    private String fromItemName;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Status status;

    @Column(length = 300)
    private String message;

    @Column(name = "requested_by", length = 64)
    private String requestedBy;

    @Column(name = "requested_at", nullable = false)
    private Instant requestedAt;

    @Column(name = "cleaned_at")
    private Instant cleanedAt;

    @Column(name = "cleared_by", length = 64)
    private String clearedBy;

    @Column(name = "cleared_at")
    private Instant clearedAt;

    protected LineChangeover() {
    }

    static LineChangeover start(String equipmentId, String cipId, String fromItemCode, String fromItemName,
                                String worker, Instant at) {
        LineChangeover c = new LineChangeover();
        c.equipmentId = equipmentId;
        c.cipId = cipId;
        c.fromItemCode = fromItemCode;
        c.fromItemName = fromItemName;
        c.status = Status.CLEANING;
        c.requestedBy = worker;
        c.requestedAt = at;
        return c;
    }

    void cleaned(Instant at) {
        if (status == Status.CLEANING) {
            status = Status.CLEANED;
            cleanedAt = at;
        }
    }

    void failed(String reason) {
        if (status == Status.CLEANING) {
            status = Status.FAILED;
            message = reason == null ? null : reason.length() > 300 ? reason.substring(0, 300) : reason;
        }
    }

    void cleared(String worker, Instant at) {
        if (status != Status.CLEANED) {
            throw new IllegalStateException("세정이 끝난 뒤에 라인 클리어런스를 확인할 수 있습니다 (현재 " + status + ")");
        }
        status = Status.CLEARED;
        clearedBy = worker;
        clearedAt = at;
    }

    public Long getId() { return id; }
    public String getEquipmentId() { return equipmentId; }
    public String getCipId() { return cipId; }
    public String getFromItemCode() { return fromItemCode; }
    public String getFromItemName() { return fromItemName; }
    public Status getStatus() { return status; }
    public String getMessage() { return message; }
    public String getRequestedBy() { return requestedBy; }
    public Instant getRequestedAt() { return requestedAt; }
    public Instant getCleanedAt() { return cleanedAt; }
    public String getClearedBy() { return clearedBy; }
    public Instant getClearedAt() { return clearedAt; }
}
