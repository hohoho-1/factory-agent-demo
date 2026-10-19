package com.factoryagent.backend.workorder;

import com.factoryagent.backend.alarm.Alarm;
import com.factoryagent.backend.alarm.AlarmRepository;
import com.factoryagent.backend.alarm.Severity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.OptionalDouble;
import java.util.TreeMap;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * 조치 이력 요약: 어떤 설비·지표에서 이상이 자주 나고, 작업자가 무엇을 원인으로 봤는지.
 * 읽기 전용이고 데모 규모(알람·지시서 수백 건)라 전체를 읽어 메모리에서 집계한다.
 */
@RestController
public class ActionStatsController {

    private static final int TOP_CAUSES = 3;

    private final AlarmRepository alarms;
    private final WorkOrderRepository workOrders;

    public ActionStatsController(AlarmRepository alarms, WorkOrderRepository workOrders) {
        this.alarms = alarms;
        this.workOrders = workOrders;
    }

    /** 이상이 많은 설비·지표 순. */
    @GetMapping("/api/action-stats")
    public List<ActionStats> stats() {
        Map<String, List<Alarm>> alarmsByKey = alarms.findAll().stream()
                .collect(Collectors.groupingBy(a -> key(a.getEquipmentId(), a.getMetric()), TreeMap::new, Collectors.toList()));
        Map<String, List<WorkOrder>> doneByKey = workOrders.findByStatus(WorkOrderStatus.COMPLETED).stream()
                .collect(Collectors.groupingBy(w -> key(w.getEquipmentId(), w.getMetric())));

        List<ActionStats> result = new ArrayList<>();
        for (Map.Entry<String, List<Alarm>> e : alarmsByKey.entrySet()) {
            List<Alarm> as = e.getValue();
            List<WorkOrder> done = doneByKey.getOrDefault(e.getKey(), List.of());
            Alarm first = as.get(0);
            result.add(new ActionStats(
                    first.getEquipmentId(),
                    first.getMetric(),
                    as.size(),
                    as.stream().filter(a -> a.getSeverity() == Severity.CRITICAL).count(),
                    as.stream().map(Alarm::getRaisedAt).max(Comparator.naturalOrder()).orElse(null),
                    done.size(),
                    done.stream().filter(w -> w.getOutcome() == ActionOutcome.RESOLVED).count(),
                    avgHandleMinutes(done),
                    topCauses(done)));
        }
        result.sort(Comparator.comparingLong(ActionStats::alarmCount).reversed());
        return result;
    }

    private static String key(String equipmentId, String metric) {
        return equipmentId + ":" + metric;
    }

    private static Double avgHandleMinutes(List<WorkOrder> done) {
        OptionalDouble seconds = done.stream()
                .filter(w -> w.getCompletedAt() != null)
                .mapToLong(w -> Duration.between(w.getCreatedAt(), w.getCompletedAt()).toSeconds())
                .average();
        // 분 단위, 소수 첫째 자리
        return seconds.isPresent() ? Math.round(seconds.getAsDouble() / 6.0) / 10.0 : null;
    }

    private static List<ActionStats.CauseCount> topCauses(List<WorkOrder> done) {
        return done.stream()
                .map(WorkOrder::getRootCause)
                .filter(Objects::nonNull)
                .map(String::trim)
                .filter(c -> !c.isEmpty())
                .collect(Collectors.groupingBy(Function.identity(), Collectors.counting()))
                .entrySet().stream()
                .sorted(Map.Entry.<String, Long>comparingByValue().reversed())
                .limit(TOP_CAUSES)
                .map(c -> new ActionStats.CauseCount(c.getKey(), c.getValue()))
                .toList();
    }
}
