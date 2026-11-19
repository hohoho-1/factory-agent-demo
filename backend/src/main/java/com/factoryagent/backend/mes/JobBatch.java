package com.factoryagent.backend.mes;

import com.fasterxml.jackson.annotation.JsonIgnore;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;

import java.time.Instant;

/** 생산 지시의 배치 1개: PLC 에 요청 → PLC 수락(진행) → 종료 → ERP 에 실적 보고. */
@Entity
@Table(name = "production_job_batch")
public class JobBatch {

    public enum Status { REQUESTED, RUNNING, COMPLETED, FAILED }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @JsonIgnore
    @ManyToOne(optional = false)
    @JoinColumn(name = "job_id")
    private ProductionJob job;

    @Column(nullable = false)
    private int seq;

    @Column(name = "batch_id", nullable = false, unique = true, length = 32)
    private String batchId;

    @Column(nullable = false)
    private int qty;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Status status;

    @Column(length = 300)
    private String message;

    @Column(name = "requested_by", length = 64)
    private String requestedBy;

    @Column(name = "requested_at", nullable = false)
    private Instant requestedAt;

    @Column(name = "completed_at")
    private Instant completedAt;

    @Column(name = "reported_at")
    private Instant reportedAt;

    protected JobBatch() {
    }

    static JobBatch request(ProductionJob job, int seq, String batchId, int qty, String worker, Instant at) {
        JobBatch b = new JobBatch();
        b.job = job;
        b.seq = seq;
        b.batchId = batchId;
        b.qty = qty;
        b.status = Status.REQUESTED;
        b.requestedBy = worker;
        b.requestedAt = at;
        return b;
    }

    /** PLC 가 요청을 받아들였다 (게이트웨이 결과 APPLIED 또는 배치 단계 태그에 이 번호가 보임). */
    public void running() {
        if (status == Status.REQUESTED) {
            status = Status.RUNNING;
        }
    }

    /** PLC 가 거부했다 (예: 다른 배치 진행 중 인터록). 다음 배치를 다시 시작할 수 있다. */
    public void failed(String reason) {
        if (status == Status.REQUESTED || status == Status.RUNNING) {
            status = Status.FAILED;
            message = reason == null ? null : reason.length() > 300 ? reason.substring(0, 300) : reason;
        }
    }

    /** 배치 종료: 지시의 진행률에 더한다. 이미 끝난 배치면 false. */
    public boolean complete(Instant at) {
        if (status == Status.COMPLETED || status == Status.FAILED) {
            return false;
        }
        status = Status.COMPLETED;
        completedAt = at;
        job.batchCompleted(this, at);
        return true;
    }

    public void reported(Instant at) {
        reportedAt = at;
    }

    public Long getId() { return id; }
    @JsonIgnore
    public ProductionJob getJob() { return job; }
    public int getSeq() { return seq; }
    public String getBatchId() { return batchId; }
    public int getQty() { return qty; }
    public Status getStatus() { return status; }
    public String getMessage() { return message; }
    public String getRequestedBy() { return requestedBy; }
    public Instant getRequestedAt() { return requestedAt; }
    public Instant getCompletedAt() { return completedAt; }
    public Instant getReportedAt() { return reportedAt; }
}
