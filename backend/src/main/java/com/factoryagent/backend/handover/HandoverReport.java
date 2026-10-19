package com.factoryagent.backend.handover;

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
 * 교대 인수인계 리포트. 대시보드가 요청하면 PENDING 으로 만들고,
 * AI 에이전트가 해당 시간대(windowFrom ~ windowTo)의 알람·조치를 요약해 DONE 으로 채운다.
 */
@Entity
@Table(name = "handover_report")
public class HandoverReport {

    public enum Status { PENDING, DONE }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "window_from", nullable = false)
    private Instant windowFrom;

    @Column(name = "window_to", nullable = false)
    private Instant windowTo;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Status status;

    @Column(name = "requested_by", length = 64)
    private String requestedBy;

    /** 작성 방식: template / llm. */
    @Column(length = 32)
    private String generator;

    @Column(length = 200)
    private String title;

    /** 마크다운 본문. */
    @Column(columnDefinition = "text")
    private String body;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "completed_at")
    private Instant completedAt;

    protected HandoverReport() {
    }

    public static HandoverReport request(Instant from, Instant to, String requestedBy) {
        HandoverReport r = new HandoverReport();
        r.windowFrom = from;
        r.windowTo = to;
        r.status = Status.PENDING;
        r.requestedBy = requestedBy;
        r.createdAt = to;
        return r;
    }

    public void complete(String title, String body, String generator, Instant at) {
        this.title = title;
        this.body = body;
        this.generator = generator;
        this.status = Status.DONE;
        this.completedAt = at;
    }

    public Long getId() { return id; }
    public Instant getWindowFrom() { return windowFrom; }
    public Instant getWindowTo() { return windowTo; }
    public Status getStatus() { return status; }
    public String getRequestedBy() { return requestedBy; }
    public String getGenerator() { return generator; }
    public String getTitle() { return title; }
    public String getBody() { return body; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getCompletedAt() { return completedAt; }
}
