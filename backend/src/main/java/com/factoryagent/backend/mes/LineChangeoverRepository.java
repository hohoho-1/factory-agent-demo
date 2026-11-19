package com.factoryagent.backend.mes;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface LineChangeoverRepository extends JpaRepository<LineChangeover, Long> {

    Optional<LineChangeover> findTopByEquipmentIdOrderByRequestedAtDesc(String equipmentId);

    Optional<LineChangeover> findByCipId(String cipId);
}
