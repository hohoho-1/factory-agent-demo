package com.factoryagent.backend.batch;

/**
 * 배치 단계가 바뀜 (배치 시작 · 단계 전환 · 배치 종료). previous 는 처음 본 설비면 null.
 * 커밋 후 SSE 'batch' 로 대시보드에 보낸다.
 */
public record BatchPhaseEvent(BatchState previous, BatchState current) {
}
