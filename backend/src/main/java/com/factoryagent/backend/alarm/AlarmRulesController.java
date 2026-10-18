package com.factoryagent.backend.alarm;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
public class AlarmRulesController {

    private final AlarmRules rules;

    public AlarmRulesController(AlarmRules rules) {
        this.rules = rules;
    }

    /** 설비 유형 → 지표 → 임계값. 대시보드 차트의 경고/위험 기준선에 쓴다. */
    @GetMapping("/api/alarm-rules")
    public Map<String, Map<String, Threshold>> rules() {
        return rules.rules();
    }
}
