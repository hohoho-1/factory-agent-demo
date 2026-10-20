package com.factoryagent.backend.batch;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface BatchRunRepository extends JpaRepository<BatchRun, Long> {

    Optional<BatchRun> findByBatchId(String batchId);

    List<BatchRun> findTop20ByOrderByStartedAtDesc();
}
