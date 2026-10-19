package com.factoryagent.backend.forecast;

import com.factoryagent.backend.alarm.Threshold;

import java.time.Instant;

/**
 * 추세 기반 예측 경보: 아직 기준을 넘지 않았지만 이 기울기로 가면 곧 경고 기준에 닿는다.
 *
 * @param limit          닿을 것으로 예상되는 기준값 (경고 기준, 없으면 위험 기준)
 * @param slopePerMinute 최근 측정값 회귀 기울기 (단위/분)
 * @param etaAt          기준 도달 예상 시각 (화면은 이 시각까지 남은 시간을 직접 센다)
 */
public record Forecast(
        String equipmentId,
        String equipmentType,
        String metric,
        String unit,
        Threshold.Direction direction,
        double limit,
        double currentValue,
        double slopePerMinute,
        long secondsToLimit,
        Instant etaAt,
        Instant raisedAt,
        Instant updatedAt
) {
}
