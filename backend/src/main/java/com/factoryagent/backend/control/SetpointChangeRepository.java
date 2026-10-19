package com.factoryagent.backend.control;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.Instant;
import java.util.List;

public interface SetpointChangeRepository extends JpaRepository<SetpointChange, Long> {

    List<SetpointChange> findTop30ByOrderByCreatedAtDesc();

    /** 승인 후 설비 응답을 기다리는 명령 중 오래된 것 (응답 없음 처리용). */
    List<SetpointChange> findByStatusAndDecidedAtBefore(SetpointChange.Status status, Instant before);
}
