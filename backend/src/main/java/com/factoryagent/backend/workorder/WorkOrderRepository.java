package com.factoryagent.backend.workorder;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface WorkOrderRepository extends JpaRepository<WorkOrder, Long> {

    List<WorkOrder> findByAlarmIdOrderByCreatedAtDesc(Long alarmId);

    List<WorkOrder> findTop50ByOrderByCreatedAtDesc();
}
