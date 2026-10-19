package com.factoryagent.backend.workorder;

import com.factoryagent.backend.alarm.Severity;

import java.util.List;

/**
 * AI 에이전트가 POST 하는 조치 지시서.
 *
 * @param causeOptions 근거 매뉴얼의 '가능 원인'에서 뽑은 짧은 이름. 작업자가 원인을 고르는 선택지가 된다
 * @param severity     에이전트가 지시서를 쓸 때 기준으로 삼은 심각도. LLM 은 수십 초 걸려 그사이 알람이 상승할 수 있으므로
 *                     저장 시점의 알람 심각도 대신 이 값을 남긴다 (없으면 알람의 현재 심각도)
 */
public record WorkOrderRequest(
        String title,
        String summary,
        String body,
        String generator,
        List<ReferenceDoc> references,
        List<String> causeOptions,
        Severity severity
) {
}
