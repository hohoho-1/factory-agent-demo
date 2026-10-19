package com.factoryagent.backend.workorder;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface WorkOrderRepository extends JpaRepository<WorkOrder, Long> {

    List<WorkOrder> findByAlarmIdOrderByCreatedAtDesc(Long alarmId);

    List<WorkOrder> findTop50ByOrderByCreatedAtDesc();

    List<WorkOrder> findByStatus(WorkOrderStatus status);

    /** 같은 설비·지표에서 조치가 끝난 지시서 (현재 알람 것은 제외), 최근 완료 순 5건. */
    List<WorkOrder> findTop5ByEquipmentIdAndMetricAndStatusAndAlarmIdNotOrderByCompletedAtDesc(
            String equipmentId, String metric, WorkOrderStatus status, Long excludeAlarmId);

    /** 같은 유형의 다른 설비에서 조치가 끝난 지시서, 최근 완료 순 3건. */
    List<WorkOrder> findTop3ByEquipmentTypeAndEquipmentIdNotAndMetricAndStatusOrderByCompletedAtDesc(
            String equipmentType, String excludeEquipmentId, String metric, WorkOrderStatus status);
}
