package com.factoryagent.backend.telemetry;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface SensorReadingRepository extends JpaRepository<SensorReading, Long> {

    /** 설비·지표 1개의 최신 측정값 (설정값 태그의 현재값 조회용). */
    Optional<SensorReading> findFirstByEquipmentIdAndMetricOrderByMeasuredAtDesc(String equipmentId, String metric);

    List<SensorReading> findByMeasuredAtAfterOrderByMeasuredAtAsc(Instant since);

    /** 설비·지표별 가장 최근 측정값 (대시보드 현재값 용도). */
    @Query(value = """
            SELECT DISTINCT ON (equipment_id, metric) *
            FROM sensor_reading
            ORDER BY equipment_id, metric, measured_at DESC
            """, nativeQuery = true)
    List<SensorReading> findLatestPerMetric();
}
