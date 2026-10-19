package com.factoryagent.backend.forecast;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
public class ForecastController {

    private final TrendForecaster forecaster;

    public ForecastController(TrendForecaster forecaster) {
        this.forecaster = forecaster;
    }

    /** 지금 진행 중인 예측 경보. */
    @GetMapping("/api/forecasts")
    public List<Forecast> current() {
        return forecaster.current();
    }
}
