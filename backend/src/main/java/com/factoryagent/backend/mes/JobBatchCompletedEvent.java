package com.factoryagent.backend.mes;

/** 생산 지시의 배치가 끝났다. 커밋 후 ERP 에 실적을 보고한다. */
public record JobBatchCompletedEvent(String batchId) {
}
