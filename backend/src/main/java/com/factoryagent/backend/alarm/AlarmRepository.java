package com.factoryagent.backend.alarm;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface AlarmRepository extends JpaRepository<Alarm, Long> {

    Optional<Alarm> findFirstByEquipmentIdAndMetricAndStatus(String equipmentId, String metric, AlarmStatus status);

    List<Alarm> findByStatusOrderByRaisedAtDesc(AlarmStatus status);

    List<Alarm> findTop50ByOrderByRaisedAtDesc();

    /** 시간대 안에 발생한 알람 + 그 전에 발생해 아직 진행 중인 알람. */
    @Query("select a from Alarm a where (a.raisedAt >= :from and a.raisedAt < :to) or a.status = com.factoryagent.backend.alarm.AlarmStatus.ACTIVE"
            + " order by a.raisedAt")
    List<Alarm> findForWindow(@Param("from") Instant from, @Param("to") Instant to);
}
