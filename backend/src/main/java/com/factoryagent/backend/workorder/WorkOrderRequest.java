package com.factoryagent.backend.workorder;

import java.util.List;

/**
 * AI 에이전트가 POST 하는 조치 지시서.
 *
 * @param causeOptions 근거 매뉴얼의 '가능 원인'에서 뽑은 짧은 이름. 작업자가 원인을 고르는 선택지가 된다
 */
public record WorkOrderRequest(
        String title,
        String summary,
        String body,
        String generator,
        List<ReferenceDoc> references,
        List<String> causeOptions
) {
}
