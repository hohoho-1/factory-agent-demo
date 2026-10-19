package com.factoryagent.backend.handover;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.Severity;
import com.factoryagent.backend.workorder.ActionOutcome;
import com.factoryagent.backend.workorder.WorkOrder;
import com.factoryagent.backend.workorder.WorkOrderStatus;

import java.time.Instant;
import java.util.List;

/**
 * 에이전트가 리포트를 쓸 재료: 시간대 안에 발생했거나 아직 진행 중인 알람,
 * 시간대 안에 작성·완료됐거나 아직 열린 지시서 (본문은 빼고 요약 필드만).
 */
public record HandoverContext(
        Instant from,
        Instant to,
        List<Alarm> alarms,
        List<WorkOrderBrief> workOrders
) {

    public record WorkOrderBrief(
            Long id,
            Long alarmId,
            String equipmentId,
            String metric,
            Severity severity,
            WorkOrderStatus status,
            String generator,
            Instant createdAt,
            String worker,
            String rootCause,
            String actionTaken,
            ActionOutcome outcome,
            Instant completedAt,
            Long supersededBy
    ) {
        public static WorkOrderBrief of(WorkOrder w) {
            return new WorkOrderBrief(w.getId(), w.getAlarmId(), w.getEquipmentId(), w.getMetric(), w.getSeverity(),
                    w.getStatus(), w.getGenerator(), w.getCreatedAt(), w.getWorker(), w.getRootCause(),
                    w.getActionTaken(), w.getOutcome(), w.getCompletedAt(), w.getSupersededBy());
        }
    }
}
