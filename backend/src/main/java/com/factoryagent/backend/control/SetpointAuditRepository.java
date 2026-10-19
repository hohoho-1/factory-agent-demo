package com.factoryagent.backend.control;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface SetpointAuditRepository extends JpaRepository<SetpointAudit, Long> {

    List<SetpointAudit> findByChangeIdOrderByAtAscIdAsc(Long changeId);
}
