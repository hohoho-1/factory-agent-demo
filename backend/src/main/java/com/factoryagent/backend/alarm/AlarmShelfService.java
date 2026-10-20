package com.factoryagent.backend.alarm;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * 알람 일시 억제. 측정값마다 확인하므로 진행 중인 억제는 메모리에 들고 있고, 바뀔 때만 DB 와 맞춘다.
 */
@Service
public class AlarmShelfService {

    private static final Logger log = LoggerFactory.getLogger(AlarmShelfService.class);
    static final int MAX_MINUTES = 120;

    private final AlarmShelfRepository repository;
    private final ApplicationEventPublisher events;
    private final List<AlarmShelf> active = new CopyOnWriteArrayList<>();
    private volatile boolean loaded;

    public AlarmShelfService(AlarmShelfRepository repository, ApplicationEventPublisher events) {
        this.repository = repository;
        this.events = events;
    }

    public record ShelveRequest(String equipmentId, String metric, Integer minutes, String reason, String worker) {
    }

    /** 이 설비·지표의 알람을 지금 억제 중이면 그 기록. */
    public Optional<AlarmShelf> shelfFor(String equipmentId, String metric, Instant at) {
        ensureLoaded();
        return active.stream().filter(s -> s.covers(equipmentId, metric, at)).findFirst();
    }

    @Transactional
    public AlarmShelf shelve(ShelveRequest req) {
        if (req == null || isBlank(req.equipmentId()) || isBlank(req.reason())) {
            throw new IllegalArgumentException("설비와 억제 사유가 필요합니다");
        }
        int minutes = req.minutes() == null ? 30 : Math.max(1, Math.min(MAX_MINUTES, req.minutes()));
        Instant now = Instant.now();
        String worker = isBlank(req.worker()) ? "현장 작업자" : req.worker().trim();
        String metric = isBlank(req.metric()) ? null : req.metric().trim();
        AlarmShelf saved = repository.save(AlarmShelf.shelve(req.equipmentId().trim(), metric, req.reason().trim(),
                worker, now, now.plus(Duration.ofMinutes(minutes))));
        ensureLoaded();
        active.add(saved);
        log.info("[ALARM SHELVED] #{} {} {} for {}min by {}: {}", saved.getId(), saved.getEquipmentId(),
                metric == null ? "(all)" : metric, minutes, worker, saved.getReason());
        events.publishEvent(new AlarmShelfEvent(saved));
        return saved;
    }

    @Transactional
    public Optional<AlarmShelf> release(Long id, String worker) {
        return repository.findById(id).map(s -> {
            if (s.getReleasedAt() == null) {
                s.release(isBlank(worker) ? "현장 작업자" : worker.trim(), Instant.now());
                repository.save(s);
                active.removeIf(a -> a.getId().equals(id));
                log.info("[ALARM SHELF RELEASED] #{} {} by {}", id, s.getEquipmentId(), s.getReleasedBy());
                events.publishEvent(new AlarmShelfEvent(s));
            }
            return s;
        });
    }

    @Transactional(readOnly = true)
    public List<AlarmShelf> active() {
        return repository.findByReleasedAtIsNullAndUntilAtAfterOrderByShelvedAtDesc(Instant.now());
    }

    private void ensureLoaded() {
        if (!loaded) {
            synchronized (this) {
                if (!loaded) {
                    active.addAll(repository.findByReleasedAtIsNullAndUntilAtAfterOrderByShelvedAtDesc(Instant.now()));
                    loaded = true;
                }
            }
        }
        Instant now = Instant.now();
        active.removeIf(s -> !s.isActive(now));
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}
