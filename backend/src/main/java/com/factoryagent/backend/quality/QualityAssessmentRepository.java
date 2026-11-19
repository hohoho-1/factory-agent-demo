package com.factoryagent.backend.quality;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface QualityAssessmentRepository extends JpaRepository<QualityAssessment, Long> {

    List<QualityAssessment> findTop50ByOrderByCreatedAtDesc();

    List<QualityAssessment> findByBatchIdOrderByCreatedAt(String batchId);

    /** ERP 에 아직 알리지 않은 확정 홀드 */
    List<QualityAssessment> findByLevelAndStatusAndHoldReportedAtIsNullOrderByDecidedAt(
            QualityAssessment.Level level, QualityAssessment.Status status);

    /** ERP 에 아직 알리지 않은 판정 (홀드를 먼저 알린 뒤에 보낸다) */
    List<QualityAssessment> findByDispositionIsNotNullAndHoldReportedAtIsNotNullAndDispositionReportedAtIsNullOrderByDispositionAt();
}
