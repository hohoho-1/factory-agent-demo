package com.factoryagent.backend.alarm;

import java.util.Optional;

/**
 * 지표 1개의 임계값. 필요한 방향만 설정하면 된다 (null = 해당 방향 검사 안 함).
 *
 * @param warnHigh 이 값 이상이면 WARNING
 * @param critHigh 이 값 이상이면 CRITICAL
 * @param warnLow  이 값 이하이면 WARNING
 * @param critLow  이 값 이하이면 CRITICAL
 */
public record Threshold(Double warnHigh, Double critHigh, Double warnLow, Double critLow) {

    /** 해제 히스테리시스: 경계값에서 5% 더 정상 쪽으로 돌아와야 알람을 해제한다 (경계 부근 깜빡임 방지). */
    static final double CLEAR_MARGIN = 0.05;

    public Optional<Breach> evaluate(double value) {
        if (critHigh != null && value >= critHigh) {
            return Optional.of(new Breach(Severity.CRITICAL, Direction.HIGH, critHigh));
        }
        if (critLow != null && value <= critLow) {
            return Optional.of(new Breach(Severity.CRITICAL, Direction.LOW, critLow));
        }
        if (warnHigh != null && value >= warnHigh) {
            return Optional.of(new Breach(Severity.WARNING, Direction.HIGH, warnHigh));
        }
        if (warnLow != null && value <= warnLow) {
            return Optional.of(new Breach(Severity.WARNING, Direction.LOW, warnLow));
        }
        return Optional.empty();
    }

    /** 활성 알람을 해제해도 될 만큼 정상 범위 안쪽으로 돌아왔는지. */
    public boolean isClear(double value) {
        Double high = warnHigh != null ? warnHigh : critHigh;
        Double low = warnLow != null ? warnLow : critLow;
        boolean highOk = high == null || value < high - Math.abs(high) * CLEAR_MARGIN;
        boolean lowOk = low == null || value > low + Math.abs(low) * CLEAR_MARGIN;
        return highOk && lowOk;
    }

    public enum Direction { HIGH, LOW }

    public record Breach(Severity severity, Direction direction, double limit) {
        public String operator() {
            return direction == Direction.HIGH ? ">=" : "<=";
        }
    }
}
