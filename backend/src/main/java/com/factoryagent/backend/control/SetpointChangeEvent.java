package com.factoryagent.backend.control;

/**
 * 설정값 변경 상태가 바뀜. 커밋 후 SSE 로 대시보드에 보내고, SENT(승인)면 MQTT 명령 토픽으로 게이트웨이에 내려보낸다.
 */
public record SetpointChangeEvent(SetpointChange change) {

    public boolean isCommand() {
        return change.getStatus() == SetpointChange.Status.SENT && change.getOrigin() == SetpointChange.Origin.AI;
    }
}
