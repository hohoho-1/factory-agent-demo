package com.factoryagent.backend.workorder;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.Severity;
import com.factoryagent.backend.alarm.Threshold;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Instant;
import java.util.List;

/** 테스트용 알람·지시서 (DB 없이 id 를 직접 넣는다). */
final class WorkOrderFixtures {

    private WorkOrderFixtures() {
    }

    static Alarm alarm(long id, String equipmentId, String metric, Severity severity) {
        Threshold.Breach breach = new Threshold.Breach(severity, Threshold.Direction.HIGH, 4.5);
        Alarm a = Alarm.raise(equipmentId, "MIXER", metric, "mm/s", breach, 5.0, Instant.now());
        ReflectionTestUtils.setField(a, "id", id);
        return a;
    }

    static WorkOrder workOrder(long id, Alarm alarm) {
        WorkOrder w = WorkOrder.of(alarm,
                new WorkOrderRequest("title", "summary", "body", "template", List.of(), List.of("원인 A", "원인 B"), null));
        ReflectionTestUtils.setField(w, "id", id);
        return w;
    }

    static WorkOrder completed(long id, Alarm alarm, String cause, ActionOutcome outcome, long handleSeconds) {
        WorkOrder w = workOrder(id, alarm);
        w.complete("tester", cause, "action", outcome, w.getCreatedAt().plusSeconds(handleSeconds));
        return w;
    }
}
