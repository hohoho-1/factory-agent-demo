package com.factoryagent.backend.mes;

import com.factoryagent.backend.batch.BatchPhaseEvent;
import com.factoryagent.backend.batch.CipStateEvent;
import com.factoryagent.backend.batch.CipStateTracker;
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
    private final LineChangeoverRepository changeovers;
    private final CipStateTracker cip;

    public MesService(ProductionJobRepository jobs, JobBatchRepository batches, BatchStateTracker tracker,
                      ApplicationEventPublisher events, Optional<Clock> clock, LineChangeoverRepository changeovers,
                      CipStateTracker cip) {
        this.jobs = jobs;
        this.batches = batches;
        this.tracker = tracker;
        this.events = events;
        this.clock = clock.orElse(Clock.systemUTC());
        this.changeovers = changeovers;
        this.cip = cip;
    }

    /**
     * 배합기 상태: 마지막으로 만든 품목과 제품 전환(세정 · 클리어런스) 진행.
     * cleanState: NONE(아직 생산 없음, 어떤 품목이든 가능) / PRODUCT(마지막 품목으로 오염, 같은 품목만 가능) /
     *             CLEANING(세정 중) / CLEANED(세정 완료, 클리어런스 대기) / CLEARED(어떤 품목이든 가능)
     */
    public record LineState(String equipmentId, String lastItemCode, String lastItemName, String lastBatchId,
                            String cleanState, LineChangeover changeover) {

        boolean allows(String itemCode) {
            return switch (cleanState) {
                case "NONE", "CLEARED" -> true;
                case "PRODUCT" -> itemCode.equals(lastItemCode);
                default -> false;
            };
        }
    }

    @Transactional(readOnly = true)
    public LineState lineState() {
        Optional<JobBatch> last = jobs.findTop20ByOrderByCreatedAtDesc().stream()
                .flatMap(j -> j.getBatches().stream())
                .filter(b -> b.getStatus() != JobBatch.Status.FAILED)
                .max(java.util.Comparator.comparing(JobBatch::getRequestedAt));
        Optional<LineChangeover> co = changeovers.findTopByEquipmentIdOrderByRequestedAtDesc(MIXER);
        // 마지막 배치 뒤에 시작한 세정만 의미가 있다
        Optional<LineChangeover> after = co.filter(c -> last.isEmpty()
                || !c.getRequestedAt().isBefore(last.get().getRequestedAt()));
        String state;
        if (after.isPresent() && after.get().getStatus() != LineChangeover.Status.FAILED) {
            state = after.get().getStatus().name();
        } else {
            state = last.isEmpty() ? "NONE" : "PRODUCT";
        }
        return new LineState(MIXER, last.map(b -> b.getJob().getItemCode()).orElse(null),
                last.map(b -> b.getJob().getItemName()).orElse(null), last.map(JobBatch::getBatchId).orElse(null),
                state, after.orElse(co.orElse(null)));
    }

    /** 작업자가 배합기 세정(CIP)을 시작한다. 커밋 후 PLC 에 세정 요청이 내려간다. */
    @Transactional
    public LineChangeover startClean(String worker) {
        Optional<BatchState> mixer = tracker.current(MIXER);
        if (mixer.isPresent() && mixer.get().running()) {
            throw new IllegalStateException("배합기에서 배치 " + mixer.get().batchId() + " 가 진행 중이라 세정할 수 없습니다");
        }
        LineState line = lineState();
        if ("CLEANING".equals(line.cleanState()) || cip.cleaning(MIXER)) {
            throw new IllegalStateException("이미 세정 중입니다");
        }
        Instant now = Instant.now(clock);
        String cipId = "CIP-" + java.time.format.DateTimeFormatter.ofPattern("MMdd-HHmmss")
                .withZone(java.time.ZoneId.systemDefault()).format(now);
        LineChangeover c = changeovers.save(LineChangeover.start(MIXER, cipId, line.lastItemCode(), line.lastItemName(),
                worker, now));
        events.publishEvent(new CleanRequestedEvent(c.getId(), MIXER, cipId, worker));
        log.info("[MES] cleaning {} requested by {} (after {})", cipId, worker, line.lastItemName());
        return c;
    }

    /** 세정이 끝난 뒤 작업자가 이전 제품의 자재 · 라벨이 라인에 남지 않았음을 확인한다. */
    @Transactional
    public LineChangeover confirmClearance(String worker) {
        LineChangeover c = changeovers.findTopByEquipmentIdOrderByRequestedAtDesc(MIXER)
                .orElseThrow(() -> new IllegalStateException("진행 중인 세정이 없습니다"));
        c.cleared(worker, Instant.now(clock));
        return changeovers.save(c);
    }

    /** PLC 세정 상태가 CLEANING → IDLE 로 바뀌면 그 세정을 완료로 기록한다. */
    @EventListener
    @Transactional
    public void onCip(CipStateEvent e) {
        if ("CLEANING".equals(e.previous()) && "IDLE".equals(e.current()) && e.previousCipId() != null) {
            changeovers.findByCipId(e.previousCipId()).ifPresent(c -> {
                c.cleaned(e.at());
                changeovers.save(c);
                log.info("[MES] cleaning {} completed", c.getCipId());
            });
        }
    }

    /** 게이트웨이의 세정 요청 결과: APPLIED 가 아니면(인터록 거부 등) 세정을 실패로 닫는다. */
    @Transactional
    public void onCleanResult(Long requestId, String status, String message) {
        if (requestId == null || "APPLIED".equals(status)) {
            return;
        }
        changeovers.findById(requestId).ifPresent(c -> {
            c.failed(message);
            changeovers.save(c);
            log.warn("[MES] cleaning {} rejected by PLC: {}", c.getCipId(), message);
        });
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
        return startNextBatch(jobId, worker, false, null, null);
    }

    @Transactional
    public JobBatch startNextBatch(Long jobId, String worker, boolean confirmOutOfOrder) {
        return startNextBatch(jobId, worker, confirmOutOfOrder, null, null);
    }

    /**
     * confirmOutOfOrder: 계획 순서상 앞선 지시가 남아 있어도 작업자가 확인하고 먼저 시작한다.
     * 확인 없이 순서를 건너뛰면 OutOfOrderException (화면이 확인을 받고 다시 보낸다).
     */
    /**
     * supervisor · supervisorReason: 오더 도중 다른 품목으로 바꿀 때 생산 책임자 승인. 승인이 있으면 계획 순서 확인은 생략한다.
     * 규칙(순서대로): 배합기 사용 중 → 세정 중 → 오더 도중 품목 전환(책임자 승인) → 품목 전환(세정 · 클리어런스) → 계획 순서.
     */
    @Transactional
    public JobBatch startNextBatch(Long jobId, String worker, boolean confirmOutOfOrder, String supervisor,
                                  String supervisorReason) {
        ProductionJob job = jobs.findById(jobId)
                .orElseThrow(() -> new IllegalArgumentException("생산 지시 #" + jobId + " 가 없습니다"));
        Optional<BatchState> mixer = tracker.current(MIXER);
        if (mixer.isPresent() && mixer.get().running()) {
            throw new IllegalStateException("배합기에서 배치 " + mixer.get().batchId() + " 가 진행 중입니다");
        }
        if (cip.cleaning(MIXER)) {
            throw new IllegalStateException("배합기 세정 중입니다");
        }
        boolean approved = supervisor != null && !supervisor.isBlank();
        Optional<ProductionJob> unfinished = jobs.findTop20ByOrderByCreatedAtDesc().stream()
                .filter(j -> !j.getId().equals(job.getId()) && j.getStatus() == ProductionJob.Status.IN_PROGRESS
                        && j.getBatchesDone() > 0 && !j.getItemCode().equals(job.getItemCode()))
                .findFirst();
        if (unfinished.isPresent() && !approved) {
            ProductionJob u = unfinished.get();
            throw new MesRuleException("SUPERVISOR_REQUIRED", u.getErpOrderNo() + "(" + u.getItemName() + ")이 "
                    + u.getBatchesTotal() + "배치 중 " + u.getBatchesDone() + "배치까지 진행 중입니다."
                    + " 오더 도중 다른 품목으로 바꾸려면 생산 책임자 승인이 필요합니다");
        }
        LineState line = lineState();
        if (!line.allows(job.getItemCode())) {
            if ("CLEANED".equals(line.cleanState())) {
                throw new MesRuleException("CLEARANCE_REQUIRED", "세정이 끝났습니다. 라인 클리어런스(이전 제품 자재 제거)를 확인하세요");
            }
            throw new MesRuleException("CHANGEOVER_REQUIRED", "품목이 바뀝니다 (" + line.lastItemName() + " → "
                    + job.getItemName() + "). 배합기 세정과 라인 클리어런스를 먼저 하세요");
        }
        if (approved) {
            confirmOutOfOrder = true;  // 책임자 승인이 순서 변경 확인을 겸한다
        }
        Optional<ProductionJob> ahead = jobs.findTop20ByOrderByCreatedAtDesc().stream()
                .filter(j -> j.getStatus() != ProductionJob.Status.COMPLETED && !j.getId().equals(job.getId()))
                .filter(j -> PLAN_ORDER.compare(j, job) < 0)
                .min(PLAN_ORDER);
        if (ahead.isPresent() && !confirmOutOfOrder) {
            throw new OutOfOrderException(ahead.get());
        }
        JobBatch b = job.openNextBatch(worker, Instant.now(clock), ahead.isPresent());
        if (approved) {
            b.approvedBy(supervisor.trim(), supervisorReason);
            log.warn("[MES] {} switched mid-order, approved by {}: {}", job.getErpOrderNo(), supervisor, supervisorReason);
        }
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
