package com.factoryagent.backend.assistant;

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
 * AI 작업 1건. 대시보드가 PENDING 으로 만들고 에이전트가 결과(마크다운)를 채워 DONE 으로 바꾼다.
 * QUESTION: 작업자의 자연어 질문 / MANUAL_PROPOSAL: 설비·지표의 조치 이력으로 매뉴얼 개선안 작성.
 */
@Entity
@Table(name = "assistant_task")
public class AssistantTask {

    public enum Type { QUESTION, MANUAL_PROPOSAL }

    public enum Status { PENDING, DONE }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private Type type;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Status status;

    @Column(length = 500)
    private String question;

    @Column(name = "equipment_id", length = 32)
    private String equipmentId;

    @Column(length = 32)
    private String metric;

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

    protected AssistantTask() {
    }

    public static AssistantTask question(String question) {
        AssistantTask t = pending(Type.QUESTION);
        t.question = question;
        return t;
    }

    public static AssistantTask manualProposal(String equipmentId, String metric) {
        AssistantTask t = pending(Type.MANUAL_PROPOSAL);
        t.equipmentId = equipmentId;
        t.metric = metric;
        return t;
    }

    private static AssistantTask pending(Type type) {
        AssistantTask t = new AssistantTask();
        t.type = type;
        t.status = Status.PENDING;
        t.createdAt = Instant.now();
        return t;
    }

    public void complete(String title, String body, String generator, Instant at) {
        this.title = title;
        this.body = body;
        this.generator = generator;
        this.status = Status.DONE;
        this.completedAt = at;
    }

    public Long getId() { return id; }
    public Type getType() { return type; }
    public Status getStatus() { return status; }
    public String getQuestion() { return question; }
    public String getEquipmentId() { return equipmentId; }
    public String getMetric() { return metric; }
    public String getGenerator() { return generator; }
    public String getTitle() { return title; }
    public String getBody() { return body; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getCompletedAt() { return completedAt; }
}
