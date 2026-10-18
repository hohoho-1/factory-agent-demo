package com.factoryagent.backend.telemetry;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.List;

public interface SensorReadingRepository extends JpaRepository<SensorReading, Long> {

    /** 설비·지표별 가장 최근 측정값 (대시보드 현재값 용도). */
    @Query(value = """
            SELECT DISTINCT ON (equipment_id, metric) *
            FROM sensor_reading
            ORDER BY equipment_id, metric, measured_at DESC
            """, nativeQuery = true)
    List<SensorReading> findLatestPerMetric();
}
