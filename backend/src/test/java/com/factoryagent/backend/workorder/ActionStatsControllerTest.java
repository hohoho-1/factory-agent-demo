package com.factoryagent.backend.workorder;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.AlarmRepository;
import com.factoryagent.backend.alarm.Severity;
import org.junit.jupiter.api.Test;

import java.util.List;

import static com.factoryagent.backend.workorder.WorkOrderFixtures.alarm;
import static com.factoryagent.backend.workorder.WorkOrderFixtures.completed;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class ActionStatsControllerTest {

    private final AlarmRepository alarms = mock(AlarmRepository.class);
    private final WorkOrderRepository workOrders = mock(WorkOrderRepository.class);
    private final ActionStatsController controller = new ActionStatsController(alarms, workOrders);

    @Test
    void aggregatesPerEquipmentMetricSortedByAlarmCount() {
        Alarm v1 = alarm(1, "MIXER-01", "vibration", Severity.WARNING);
        Alarm v2 = alarm(2, "MIXER-01", "vibration", Severity.CRITICAL);
        Alarm v3 = alarm(3, "MIXER-01", "vibration", Severity.CRITICAL);
        Alarm c1 = alarm(4, "MIXER-01", "current", Severity.WARNING);
        when(alarms.findAll()).thenReturn(List.of(c1, v1, v2, v3));
        when(workOrders.findByStatus(WorkOrderStatus.COMPLETED)).thenReturn(List.of(
                completed(10, v1, "베어링 윤활 부족", ActionOutcome.RESOLVED, 60),
                completed(11, v2, " 베어링 윤활 부족 ", ActionOutcome.RESOLVED, 180),
                completed(12, v3, "임펠러 고착", ActionOutcome.UNRESOLVED, 120)));

        List<ActionStats> stats = controller.stats();

        assertThat(stats).extracting(ActionStats::metric).containsExactly("vibration", "current");
        ActionStats vib = stats.get(0);
        assertThat(vib.alarmCount()).isEqualTo(3);
        assertThat(vib.criticalCount()).isEqualTo(2);
        assertThat(vib.completedCount()).isEqualTo(3);
        assertThat(vib.resolvedCount()).isEqualTo(2);
        assertThat(vib.avgHandleMinutes()).isEqualTo(2.0);
        // 앞뒤 공백은 같은 원인으로 묶는다
        assertThat(vib.topCauses()).first()
                .isEqualTo(new ActionStats.CauseCount("베어링 윤활 부족", 2));

        ActionStats cur = stats.get(1);
        assertThat(cur.completedCount()).isZero();
        assertThat(cur.avgHandleMinutes()).isNull();
        assertThat(cur.topCauses()).isEmpty();
    }
}
