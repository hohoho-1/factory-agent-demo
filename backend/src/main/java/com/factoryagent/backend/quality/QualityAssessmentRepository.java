package com.factoryagent.backend.quality;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface QualityAssessmentRepository extends JpaRepository<QualityAssessment, Long> {

    List<QualityAssessment> findTop50ByOrderByCreatedAtDesc();

    List<QualityAssessment> findByBatchIdOrderByCreatedAt(String batchId);
}
