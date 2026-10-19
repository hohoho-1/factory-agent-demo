package com.factoryagent.backend.assistant;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AssistantTaskRepository extends JpaRepository<AssistantTask, Long> {

    List<AssistantTask> findTop20ByOrderByCreatedAtDesc();
}
