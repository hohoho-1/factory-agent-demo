package com.factoryagent.backend.quality;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 품질 홀드와 판정을 ERP 에 알린다 (MES → ERP).
 * - 품질팀이 홀드를 승인하면: POST /erp/quality-holds  → ERP 가 그 배치의 완제품을 '품질 보류' 재고로 둔다
 *   (배치가 아직 돌고 있으면 기억해 뒀다가 실적이 올 때 보류로 받는다)
 * - 검사 판정이 나면: POST /erp/quality-holds/{배치}/disposition → 합격이면 가용 재고로, 불합격이면 폐기 + 재생산 오더
 * ERP 가 꺼져 있으면 15초마다 다시 보낸다. 홀드를 먼저 알린 뒤에만 판정을 보낸다.
 */
@Component
public class QualityErpReporter {

    private static final Logger log = LoggerFactory.getLogger(QualityErpReporter.class);

    private final QualityAssessmentRepository repository;
    private final RestClient erp;

    public QualityErpReporter(QualityAssessmentRepository repository,
                              @Value("${app.erp.base-url:http://127.0.0.1:8090}") String baseUrl) {
        this.repository = repository;
        this.erp = RestClient.builder().baseUrl(baseUrl).build();
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onChanged(QualityAssessmentEvent e) {
        reportPending();
    }

    @Scheduled(fixedDelay = 15_000)
    public synchronized void reportPending() {
        for (QualityAssessment q : repository.findByLevelAndStatusAndHoldReportedAtIsNullOrderByDecidedAt(
                QualityAssessment.Level.HOLD, QualityAssessment.Status.APPROVED)) {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("batchId", q.getBatchId());
            body.put("assessmentId", q.getId());
            body.put("reason", q.getBasis());
            body.put("approvedBy", q.getDecidedBy());
            if (!send("/erp/quality-holds", body, q.getBatchId(), "hold")) {
                return;
            }
            q.holdReported(Instant.now());
            repository.save(q);
        }
        for (QualityAssessment q : repository
                .findByDispositionIsNotNullAndHoldReportedAtIsNotNullAndDispositionReportedAtIsNullOrderByDispositionAt()) {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("result", q.getDisposition().name());
            body.put("by", q.getDispositionBy());
            body.put("note", q.getDispositionNote());
            if (!send("/erp/quality-holds/" + q.getBatchId() + "/disposition", body, q.getBatchId(), "disposition")) {
                return;
            }
            q.dispositionReported(Instant.now());
            repository.save(q);
        }
    }

    private boolean send(String path, Map<String, Object> body, String batchId, String what) {
        try {
            erp.post().uri(path).body(body).retrieve().toBodilessEntity();
            log.info("[QUALITY] {} of batch {} reported to ERP", what, batchId);
            return true;
        } catch (RestClientException e) {
            log.warn("[QUALITY] ERP {} report for {} failed, will retry: {}", what, batchId, e.getMessage());
            return false;
        }
    }
}
