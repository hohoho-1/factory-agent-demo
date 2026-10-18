package com.factoryagent.backend.telemetry;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/readings")
public class TelemetryController {

    private final TelemetryService telemetryService;

    public TelemetryController(TelemetryService telemetryService) {
        this.telemetryService = telemetryService;
    }

    /** 설비·지표별 최신값. */
    @GetMapping("/latest")
    public List<SensorReading> latest() {
        return telemetryService.latest();
    }
}
