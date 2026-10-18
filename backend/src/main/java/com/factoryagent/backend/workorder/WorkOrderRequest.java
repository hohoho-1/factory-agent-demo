package com.factoryagent.backend.workorder;

import java.util.List;

/** AI 에이전트가 POST 하는 조치 지시서. */
public record WorkOrderRequest(
        String title,
        String summary,
        String body,
        String generator,
        List<ReferenceDoc> references
) {
}
