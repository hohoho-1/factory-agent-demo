package com.factoryagent.backend.assistant;

/** AI 작업 요청(REQUESTED → MQTT 로 에이전트에) 또는 작성 완료(COMPLETED). 둘 다 SSE 로 대시보드에 보낸다. */
public record AssistantEvent(Type type, AssistantTask task) {

    public enum Type { REQUESTED, COMPLETED }
}
