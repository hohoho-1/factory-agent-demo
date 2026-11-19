package com.factoryagent.backend.mes;

import com.factoryagent.backend.batch.BatchPhaseEvent;
import com.factoryagent.backend.batch.BatchState;
import com.factoryagent.backend.batch.BatchStateTracker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;

/**
 * MES 생산 지시 (ISA-95 레벨 3): ERP 생산 오더를 받아 배치로 나눠 현장에서 돌리고, 끝난 배치의 실적을 ERP 에 올린다.
 *
 *   ERP 생산 오더 ─(현장 지시)→ 생산 지시 ─(작업자 '배치 시작')→ PLC 배치 요청(OPC UA batchRequest)
 *     → PLC 수락 · 배치 진행 → 배치 종료(배치 단계 태그) → ERP 에 실적 보고(수량 · 배치 번호)
 *
 * 배치 시작은 사람이 누른다 (자율성 '승인 후 실행'). PLC 는 다른 배치가 돌고 있으면 인터록으로 거부한다.
 */
@Service
public class MesService {

    private static final Logger log = LoggerFactory.getLogger(MesService.class);
    static final String MIXER = "MIXER-01";

    private final ProductionJobRepository jobs;
    private final JobBatchRepository batches;
    private final BatchStateTracker tracker;
    private final ApplicationEventPublisher events;
    private final Clock clock;

    public MesService(ProductionJobRepository jobs, JobBatchRepository batches, BatchStateTracker tracker,
                      ApplicationEventPublisher events, Optional<Clock> clock) {
        this.jobs = jobs;
        this.batches = batches;
        this.tracker = tracker;
        this.events = events;
        this.clock = clock.orElse(Clock.systemUTC());
    }

    public record JobRequest(String erpOrderNo, String itemCode, String itemName, Integer qty, Integer batches,
                             LocalDate plannedStart) {
    }

    /** 계획 순서상 앞선 지시가 아직 끝나지 않았다. 작업자가 확인하면 '순서 변경'으로 시작할 수 있다. */
    public static class OutOfOrderException extends RuntimeException {
        private final String aheadOrderNo;

        OutOfOrderException(ProductionJob ahead) {
            super("계획 순서상 " + ahead.getErpOrderNo()
                    + (ahead.getPlannedStart() == null ? "" : " (" + ahead.getPlannedStart() + " 시작 계획)")
                    + " 이 먼저입니다");
            this.aheadOrderNo = ahead.getErpOrderNo();
        }

        public String getAheadOrderNo() {
            return aheadOrderNo;
        }
    }

    /** 계획 순서: 끝나지 않은 지시 먼저, 계획 시작일 순(없으면 뒤로), 같으면 받은 순. */
    static final Comparator<ProductionJob> PLAN_ORDER = Comparator
            .comparing((ProductionJob j) -> j.getStatus() == ProductionJob.Status.COMPLETED)
            .thenComparing(ProductionJob::getPlannedStart, Comparator.nullsLast(Comparator.naturalOrder()))
            .thenComparing(ProductionJob::getCreatedAt);

    /** ERP 가 내려 준 생산 오더를 생산 지시로 받는다. 같은 오더를 두 번 보내면 처음 것을 돌려준다. */
    @Transactional
    public ProductionJob receive(JobRequest req) {
        if (req.erpOrderNo() == null || req.erpOrderNo().isBlank() || req.itemCode() == null || req.itemName() == null
                || req.qty() == null || req.qty() <= 0 || req.batches() == null || req.batches() <= 0
                || req.batches() > req.qty()) {
            throw new IllegalArgumentException("생산 지시 형식이 틀렸습니다 (오더번호 · 품목 · 수량 · 배치 수)");
        }
        return jobs.findByErpOrderNo(req.erpOrderNo()).orElseGet(() -> {
            ProductionJob job = jobs.save(ProductionJob.receive(req.erpOrderNo().trim(), req.itemCode(), req.itemName(),
                    req.qty(), req.batches(), req.plannedStart(), Instant.now(clock)));
            log.info("[MES] job {} received from ERP: {} x{} in {} batches", job.getErpOrderNo(), job.getItemName(),
                    job.getQty(), job.getBatchesTotal());
            return job;
        });
    }

    /** 최근 지시 20건을 계획 순서로. */
    @Transactional(readOnly = true)
    public List<ProductionJob> recent() {
        return jobs.findTop20ByOrderByCreatedAtDesc().stream().sorted(PLAN_ORDER).toList();
    }

    /**
     * 작업자가 다음 배치를 시작한다. 배합기에서 다른 배치가 돌고 있으면 PLC 까지 가기 전에 막는다
     * (PLC 인터록도 다시 막는다). 커밋 후 PLC 에 배치 요청 명령이 내려간다.
     */
    @Transactional
    public JobBatch startNextBatch(Long jobId, String worker) {
        return startNextBatch(jobId, worker, false);
    }

    /**
     * confirmOutOfOrder: 계획 순서상 앞선 지시가 남아 있어도 작업자가 확인하고 먼저 시작한다.
     * 확인 없이 순서를 건너뛰면 OutOfOrderException (화면이 확인을 받고 다시 보낸다).
     */
    @Transactional
    public JobBatch startNextBatch(Long jobId, String worker, boolean confirmOutOfOrder) {
        ProductionJob job = jobs.findById(jobId)
                .orElseThrow(() -> new IllegalArgumentException("생산 지시 #" + jobId + " 가 없습니다"));
        Optional<BatchState> mixer = tracker.current(MIXER);
        if (mixer.isPresent() && mixer.get().running()) {
            throw new IllegalStateException("배합기에서 배치 " + mixer.get().batchId() + " 가 진행 중입니다");
        }
        Optional<ProductionJob> ahead = jobs.findTop20ByOrderByCreatedAtDesc().stream()
                .filter(j -> j.getStatus() != ProductionJob.Status.COMPLETED && !j.getId().equals(job.getId()))
                .filter(j -> PLAN_ORDER.compare(j, job) < 0)
                .min(PLAN_ORDER);
        if (ahead.isPresent() && !confirmOutOfOrder) {
            throw new OutOfOrderException(ahead.get());
        }
        JobBatch b = job.openNextBatch(worker, Instant.now(clock), ahead.isPresent());
        if (ahead.isPresent()) {
            log.warn("[MES] {} started before {} by {} (out of plan order)", job.getErpOrderNo(),
                    ahead.get().getErpOrderNo(), worker);
        }
        jobs.save(job);
        JobBatch saved = job.getBatches().get(job.getBatches().size() - 1);
        events.publishEvent(new JobBatchRequestedEvent(saved.getId(), MIXER, b.getBatchId(), job.getItemName(), worker));
        log.info("[MES] {} batch {} requested by {}", job.getErpOrderNo(), b.getBatchId(), worker);
        return saved;
    }

    /** 게이트웨이의 배치 요청 결과: APPLIED 면 진행, 그 밖(인터록 거부 · 실패)이면 실패로 닫는다. */
    @Transactional
    public void onCommandResult(Long requestId, String status, String message) {
        if (requestId == null) {
            return;
        }
        batches.findById(requestId).ifPresent(b -> {
            if ("APPLIED".equals(status)) {
                b.running();
            } else {
                b.failed(message);
                log.warn("[MES] batch {} rejected by PLC: {} {}", b.getBatchId(), status, message);
            }
            batches.save(b);
        });
    }

    /**
     * 배치 단계 태그로 배치 시작 · 종료를 본다. 생산 지시의 배치 번호가 단계 태그에 보이면 진행,
     * 그 번호가 사라지면(다음 배치 · 대기) 종료로 보고 ERP 보고를 예약한다.
     */
    @EventListener
    @Transactional
    public void onPhase(BatchPhaseEvent e) {
        BatchState prev = e.previous();
        BatchState cur = e.current();
        if (cur.batchId() != null) {
            batches.findByBatchId(cur.batchId()).ifPresent(b -> {
                b.running();
                batches.save(b);
            });
        }
        if (prev != null && prev.batchId() != null && !prev.batchId().equals(cur.batchId())) {
            batches.findByBatchId(prev.batchId()).ifPresent(b -> {
                if (b.complete(cur.phaseStartedAt())) {
                    jobs.save(b.getJob());
                    log.info("[MES] batch {} completed ({} of {} for {})", b.getBatchId(), b.getJob().getBatchesDone(),
                            b.getJob().getBatchesTotal(), b.getJob().getErpOrderNo());
                    events.publishEvent(new JobBatchCompletedEvent(b.getBatchId()));
                }
            });
        }
    }
}
