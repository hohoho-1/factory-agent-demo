package com.factoryagent.backend.mes;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 끝난 배치의 생산 실적을 ERP 에 보고한다 (MES → ERP, ISA-95 레벨 3 → 4).
 * 보고 내용은 오더번호 · 배치 번호 · 수량 · 종료 시각뿐이다. 원료 소비는 ERP 가 BOM 표준량으로 계산한다 (백플러시).
 * ERP 가 꺼져 있으면 보고하지 못한 배치를 주기적으로 다시 보낸다. ERP 는 배치 번호로 중복 보고를 무시한다.
 */
@Component
public class ErpReporter {

    private static final Logger log = LoggerFactory.getLogger(ErpReporter.class);

    private final JobBatchRepository batches;
    private final RestClient erp;

    public ErpReporter(JobBatchRepository batches, @Value("${app.erp.base-url:http://127.0.0.1:8090}") String baseUrl) {
        this.batches = batches;
        this.erp = RestClient.builder().baseUrl(baseUrl).build();
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onCompleted(JobBatchCompletedEvent e) {
        reportPending();
    }

    @Scheduled(fixedDelay = 15_000)
    @Transactional
    public synchronized void reportPending() {
        for (JobBatch b : batches.findByStatusAndReportedAtIsNullOrderByCompletedAt(JobBatch.Status.COMPLETED)) {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("batchId", b.getBatchId());
            body.put("seq", b.getSeq());
            body.put("qty", b.getQty());
            body.put("completedAt", b.getCompletedAt());
            try {
                erp.post().uri("/erp/production-orders/{no}/actuals", b.getJob().getErpOrderNo())
                        .body(body).retrieve().toBodilessEntity();
                b.reported(Instant.now());
                batches.save(b);
                log.info("[MES] batch {} actual reported to ERP ({} pouches)", b.getBatchId(), b.getQty());
            } catch (RestClientException ex) {
                log.warn("[MES] ERP report for {} failed, will retry: {}", b.getBatchId(), ex.getMessage());
                return;
            }
        }
    }
}
