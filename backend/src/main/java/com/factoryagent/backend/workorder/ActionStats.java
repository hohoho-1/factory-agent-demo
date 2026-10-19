package com.factoryagent.backend.workorder;

import java.time.Instant;
import java.util.List;

/**
 * 설비·지표별 이상 발생과 작업자 조치 요약.
 *
 * @param avgHandleMinutes 지시서 작성부터 조치 완료까지 평균 (완료 건이 없으면 null)
 * @param topCauses        작업자가 입력한 원인 중 많은 순 최대 3개
 */
public record ActionStats(
        String equipmentId,
        String metric,
        long alarmCount,
        long criticalCount,
        Instant lastRaisedAt,
        long completedCount,
        long resolvedCount,
        Double avgHandleMinutes,
        List<CauseCount> topCauses
) {
    public record CauseCount(String cause, long count) {
    }
}
