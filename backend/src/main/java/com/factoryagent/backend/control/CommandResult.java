package com.factoryagent.backend.control;

/**
 * 게이트웨이가 factory/line1/commands/results 로 보고한 설정값 쓰기 결과.
 *
 * @param requestId 백엔드가 보낸 명령이면 setpoint_change id, 게이트웨이로 직접 들어온 명령이면 null
 * @param status    APPLIED / INTERLOCKED / FAILED
 * @param code      OPC UA 상태 코드 이름 (Good, BadOutOfRange, BadInvalidState …)
 */
public record CommandResult(Long requestId, String equipmentId, String tag, Double requested, String status,
                            String code, String message, Double before, Double after) {

    SetpointChange.Status toStatus() {
        if ("APPLIED".equals(status)) {
            return SetpointChange.Status.APPLIED;
        }
        return "INTERLOCKED".equals(status) ? SetpointChange.Status.INTERLOCKED : SetpointChange.Status.FAILED;
    }
}
