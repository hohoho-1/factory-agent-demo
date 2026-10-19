package com.factoryagent.backend.workorder;

/** 작업자가 조치를 마치고 입력하는 결과. 다음 지시서의 '과거 유사 조치 이력'이 된다. */
public record ActionResultRequest(
        String worker,
        String rootCause,
        String actionTaken,
        ActionOutcome outcome
) {
}
