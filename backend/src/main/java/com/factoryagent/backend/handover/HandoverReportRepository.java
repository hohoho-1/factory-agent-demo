package com.factoryagent.backend.handover;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface HandoverReportRepository extends JpaRepository<HandoverReport, Long> {

    List<HandoverReport> findTop10ByOrderByCreatedAtDesc();
}
