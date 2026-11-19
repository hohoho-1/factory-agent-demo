package com.factoryagent.backend.mes;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface JobBatchRepository extends JpaRepository<JobBatch, Long> {

    Optional<JobBatch> findByBatchId(String batchId);

    List<JobBatch> findByStatusAndReportedAtIsNullOrderByCompletedAt(JobBatch.Status status);
}
