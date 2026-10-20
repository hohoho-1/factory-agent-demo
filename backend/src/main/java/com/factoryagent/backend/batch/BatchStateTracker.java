package com.factoryagent.backend.batch;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 설비별 현재 배치 단계. 텔레메트리의 state(batchPhase · batchId · recipe)로 갱신한다.
 * 알람 판정이 단계별 기준을 고를 때 쓴다. 메모리에만 두고, 재시작하면 다음 텔레메트리에서 다시 채워진다.
 */
@Component
public class BatchStateTracker {

    private static final Logger log = LoggerFactory.getLogger(BatchStateTracker.class);

    private final Map<String, BatchState> states = new ConcurrentHashMap<>();

    /** 상태 태그를 반영한다. 단계나 배치 번호가 바뀌었으면 이벤트를 돌려준다. */
    public Optional<BatchPhaseEvent> observe(String equipmentId, Map<String, String> state, Instant at) {
        if (state == null || state.get("batchPhase") == null || state.get("batchPhase").isBlank()) {
            return Optional.empty();
        }
        String phase = state.get("batchPhase").trim();
        String batchId = blankToNull(state.get("batchId"));
        BatchState previous = states.get(equipmentId);
        if (previous != null && previous.phase().equals(phase) && java.util.Objects.equals(previous.batchId(), batchId)) {
            return Optional.empty();
        }
        BatchState current = new BatchState(equipmentId, phase, batchId, blankToNull(state.get("recipe")), at);
        states.put(equipmentId, current);
        log.info("[BATCH] {} {} -> {} ({})", equipmentId, previous == null ? "-" : previous.phase(), phase,
                batchId == null ? (previous == null ? "-" : previous.batchId()) : batchId);
        return Optional.of(new BatchPhaseEvent(previous, current));
    }

    public Optional<BatchState> current(String equipmentId) {
        return Optional.ofNullable(states.get(equipmentId));
    }

    public List<BatchState> all() {
        return List.copyOf(states.values());
    }

    private static String blankToNull(String s) {
        return s == null || s.isBlank() ? null : s.trim();
    }
}
