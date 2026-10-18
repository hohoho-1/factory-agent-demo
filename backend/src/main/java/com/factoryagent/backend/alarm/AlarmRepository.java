package com.factoryagent.backend.alarm;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface AlarmRepository extends JpaRepository<Alarm, Long> {

    Optional<Alarm> findFirstByEquipmentIdAndMetricAndStatus(String equipmentId, String metric, AlarmStatus status);

    List<Alarm> findByStatusOrderByRaisedAtDesc(AlarmStatus status);

    List<Alarm> findTop50ByOrderByRaisedAtDesc();
}
