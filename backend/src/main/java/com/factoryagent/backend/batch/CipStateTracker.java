package com.factoryagent.backend.batch;

import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/** 텔레메트리 state 의 cipState · cipId 를 지켜보다가 바뀌면 이벤트를 돌려준다 (가상 PLC 모드에서만 온다). */
@Component
public class CipStateTracker {

    private final Map<String, String[]> states = new ConcurrentHashMap<>();  // 설비 → [cipState, cipId]

    public Optional<CipStateEvent> observe(String equipmentId, Map<String, String> state, Instant at) {
        if (state == null || state.get("cipState") == null || state.get("cipState").isBlank()) {
            return Optional.empty();
        }
        String cur = state.get("cipState").trim();
        String id = state.getOrDefault("cipId", "").trim();
        String[] prev = states.put(equipmentId, new String[]{cur, id});
        if (prev == null || prev[0].equals(cur)) {
            return Optional.empty();
        }
        return Optional.of(new CipStateEvent(equipmentId, prev[0], cur, prev[1], at));
    }

    public boolean cleaning(String equipmentId) {
        String[] s = states.get(equipmentId);
        return s != null && "CLEANING".equals(s[0]);
    }
}
