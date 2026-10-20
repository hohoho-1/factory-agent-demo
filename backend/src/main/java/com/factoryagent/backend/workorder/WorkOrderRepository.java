package com.factoryagent.backend.workorder;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import java.util.List;

public interface WorkOrderRepository extends JpaRepository<WorkOrder, Long> {

    List<WorkOrder> findByAlarmIdOrderByCreatedAtDesc(Long alarmId);

    List<WorkOrder> findTop50ByOrderByCreatedAtDesc();

    List<WorkOrder> findByStatus(WorkOrderStatus status);

    /** AI 질의 재료: 최근 지시서. */
    List<WorkOrder> findTop200ByCreatedAtAfterOrderByCreatedAtDesc(Instant after);

    /** 매뉴얼 개선 제안 재료: 설비·지표의 조치 완료 지시서. */
    List<WorkOrder> findTop100ByEquipmentIdAndMetricAndStatusOrderByCompletedAtDesc(
            String equipmentId, String metric, WorkOrderStatus status);

    /** 매뉴얼 개선 제안 재료: 같은 유형 다른 설비의 조치 완료 지시서. */
    List<WorkOrder> findTop50ByEquipmentTypeAndEquipmentIdNotAndMetricAndStatusOrderByCompletedAtDesc(
            String equipmentType, String excludeEquipmentId, String metric, WorkOrderStatus status);

    /** 시간대 안에 작성·완료된 지시서 + 아직 열린(미확인·조치 중) 지시서. 인수인계 리포트 재료. */
    @Query("select w from WorkOrder w where (w.createdAt >= :from and w.createdAt < :to)"
            + " or (w.completedAt >= :from and w.completedAt < :to)"
            + " or w.status in (com.factoryagent.backend.workorder.WorkOrderStatus.OPEN,"
            + " com.factoryagent.backend.workorder.WorkOrderStatus.ACKNOWLEDGED)"
            + " order by w.createdAt")
    List<WorkOrder> findForWindow(@Param("from") Instant from, @Param("to") Instant to);

    /** 알람들에 대해 작성된 지시서 (배치 기록용). */
    List<WorkOrder> findByAlarmIdInOrderByCreatedAt(java.util.Collection<Long> alarmIds);

    /** 같은 설비·지표에서 조치가 끝난 지시서 (현재 알람 것은 제외), 최근 완료 순 5건. */
    List<WorkOrder> findTop5ByEquipmentIdAndMetricAndStatusAndAlarmIdNotOrderByCompletedAtDesc(
            String equipmentId, String metric, WorkOrderStatus status, Long excludeAlarmId);

    /** 같은 유형의 다른 설비에서 조치가 끝난 지시서, 최근 완료 순 3건. */
    List<WorkOrder> findTop3ByEquipmentTypeAndEquipmentIdNotAndMetricAndStatusOrderByCompletedAtDesc(
            String equipmentType, String excludeEquipmentId, String metric, WorkOrderStatus status);
}
