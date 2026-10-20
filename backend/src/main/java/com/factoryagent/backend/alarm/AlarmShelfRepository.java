package com.factoryagent.backend.alarm;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.Instant;
import java.util.List;

public interface AlarmShelfRepository extends JpaRepository<AlarmShelf, Long> {

    /** 아직 풀리지 않았고 시간이 남은 억제. */
    List<AlarmShelf> findByReleasedAtIsNullAndUntilAtAfterOrderByShelvedAtDesc(Instant at);
}
