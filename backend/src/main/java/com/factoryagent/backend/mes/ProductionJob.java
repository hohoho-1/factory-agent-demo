package com.factoryagent.backend.mes;

import jakarta.persistence.CascadeType;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.OneToMany;
import jakarta.persistence.OrderBy;
import jakarta.persistence.Table;

import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

/**
 * MES 생산 지시: ERP 생산 오더 1건을 현장에서 받은 것. 배합 배치 여러 개로 나눠 돈다.
 * 배치 번호는 MES 가 정한다 ({ERP 오더번호}-{순번}): 어느 배치가 어느 주문의 것인지 끝까지 추적된다.
 */
@Entity
@Table(name = "production_job")
public class ProductionJob {

    public enum Status { RECEIVED, IN_PROGRESS, COMPLETED }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "erp_order_no", nullable = false, unique = true, length = 32)
    private String erpOrderNo;

    @Column(name = "item_code", nullable = false, length = 32)
    private String itemCode;

    @Column(name = "item_name", nullable = false, length = 100)
    private String itemName;

    @Column(nullable = false)
    private int qty;

    @Column(name = "batches_total", nullable = false)
    private int batchesTotal;

    @Column(name = "batches_done", nullable = false)
    private int batchesDone;

    @Column(name = "produced_qty", nullable = false)
    private int producedQty;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Status status;

    /** ERP 생산 계획의 시작일. MES 는 이 순서로 지시를 보여 준다 */
    @Column(name = "planned_start")
    private LocalDate plannedStart;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "completed_at")
    private Instant completedAt;

    @OneToMany(mappedBy = "job", cascade = CascadeType.ALL, fetch = FetchType.EAGER)
    @OrderBy("seq")
    private List<JobBatch> batches = new ArrayList<>();

    protected ProductionJob() {
    }

    public static ProductionJob receive(String erpOrderNo, String itemCode, String itemName, int qty, int batchesTotal,
                                        LocalDate plannedStart, Instant at) {
        ProductionJob j = new ProductionJob();
        j.erpOrderNo = erpOrderNo;
        j.itemCode = itemCode;
        j.itemName = itemName;
        j.qty = qty;
        j.batchesTotal = batchesTotal;
        j.plannedStart = plannedStart;
        j.status = Status.RECEIVED;
        j.createdAt = at;
        return j;
    }

    /** 배치 하나에 들어갈 수량: 전체를 배치 수로 나누고 나머지는 앞 배치에 하나씩 더한다 (합계가 정확히 맞게). */
    int qtyOfBatch(int seq) {
        int base = qty / batchesTotal;
        return base + (seq <= qty % batchesTotal ? 1 : 0);
    }

    /** 다음 배치를 연다. 진행 중이거나 요청 중인 배치가 있거나, 배치를 다 돌았으면 IllegalStateException. */
    public JobBatch openNextBatch(String worker, Instant at) {
        return openNextBatch(worker, at, false);
    }

    /** outOfOrder: 계획 순서상 앞선 지시를 두고 작업자가 확인 후 먼저 시작했다 (기록으로 남긴다). */
    public JobBatch openNextBatch(String worker, Instant at, boolean outOfOrder) {
        if (batches.stream().anyMatch(b -> b.getStatus() == JobBatch.Status.REQUESTED
                || b.getStatus() == JobBatch.Status.RUNNING)) {
            throw new IllegalStateException("이 지시의 배치가 아직 진행 중입니다");
        }
        if (batchesDone >= batchesTotal) {
            throw new IllegalStateException("배치를 모두 마친 지시입니다");
        }
        int seq = batches.size() + 1;
        // 실패한 배치는 번호를 다시 쓰지 않는다 (기록이 남도록). 수량은 아직 끝나지 않은 순번 기준
        int qtySeq = batchesDone + 1;
        JobBatch b = JobBatch.request(this, seq, String.format("%s-%02d", erpOrderNo, seq), qtyOfBatch(qtySeq), worker, at,
                outOfOrder);
        batches.add(b);
        status = Status.IN_PROGRESS;
        return b;
    }

    void batchCompleted(JobBatch b, Instant at) {
        batchesDone++;
        producedQty += b.getQty();
        if (batchesDone >= batchesTotal) {
            status = Status.COMPLETED;
            completedAt = at;
        }
    }

    public Long getId() { return id; }
    public String getErpOrderNo() { return erpOrderNo; }
    public String getItemCode() { return itemCode; }
    public String getItemName() { return itemName; }
    public int getQty() { return qty; }
    public int getBatchesTotal() { return batchesTotal; }
    public int getBatchesDone() { return batchesDone; }
    public int getProducedQty() { return producedQty; }
    public Status getStatus() { return status; }
    public LocalDate getPlannedStart() { return plannedStart; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getCompletedAt() { return completedAt; }
    public List<JobBatch> getBatches() { return batches; }
}
