package com.factoryagent.backend.handover;

/**
 * 리포트 생성 요청(REQUESTED) 또는 작성 완료(COMPLETED).
 * 커밋 후 REQUESTED 는 MQTT 로 에이전트에, 둘 다 SSE 로 대시보드에 보낸다.
 */
public record HandoverEvent(Type type, HandoverReport report) {

    public enum Type { REQUESTED, COMPLETED }
}
