package com.factoryagent.backend.mes;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface ProductionJobRepository extends JpaRepository<ProductionJob, Long> {

    Optional<ProductionJob> findByErpOrderNo(String erpOrderNo);

    List<ProductionJob> findTop20ByOrderByCreatedAtDesc();
}
