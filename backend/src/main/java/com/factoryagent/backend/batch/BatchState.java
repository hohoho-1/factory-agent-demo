package com.factoryagent.backend.batch;

import java.time.Instant;

/**
 * 설비 1대의 현재 배치 상태 (가상 PLC 의 문자열 상태 태그에서 온다).
 *
 * @param phase          IDLE / CHARGING / HEATING / EMULSIFYING / COOLING / DISCHARGING
 * @param batchId        진행 중인 배치 번호 (대기 중이면 null)
 * @param phaseStartedAt 이 단계가 시작된 시각 (백엔드가 단계 변화를 처음 본 측정 시각)
 */
public record BatchState(String equipmentId, String phase, String batchId, String recipe, Instant phaseStartedAt) {

    public static final String IDLE = "IDLE";

    public boolean running() {
        return batchId != null && !IDLE.equals(phase);
    }

    public long secondsInPhase(Instant at) {
        return Math.max(0, java.time.Duration.between(phaseStartedAt, at).toSeconds());
    }
}
