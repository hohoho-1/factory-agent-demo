package com.factoryagent.backend.workorder;

/** 작업자가 지시서를 확인했다는 표시. */
public record AcknowledgeRequest(String worker) {
}
