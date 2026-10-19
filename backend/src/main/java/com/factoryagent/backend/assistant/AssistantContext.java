package com.factoryagent.backend.assistant;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.handover.HandoverContext.WorkOrderBrief;

import java.util.List;

/**
 * 에이전트가 AI 작업을 할 재료.
 * QUESTION: 최근 7일 알람·지시서 / MANUAL_PROPOSAL: 해당 설비·지표의 알람과 조치 완료 지시서(+같은 유형 다른 설비).
 * 설비·지표별 통계는 에이전트가 /api/action-stats 로 따로 읽는다.
 */
public record AssistantContext(
        AssistantTask task,
        List<Alarm> alarms,
        List<WorkOrderBrief> workOrders
) {
}
