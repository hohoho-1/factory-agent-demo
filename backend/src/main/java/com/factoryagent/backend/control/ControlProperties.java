package com.factoryagent.backend.control;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;
import java.util.List;
import java.util.Optional;

/**
 * 원격으로 바꿀 수 있는 설정값과 운전 범위 (application.yml 의 app.control).
 * 이 범위는 백엔드가 AI 제안·승인 때 거르는 '운전 범위'다. PLC 안의 인터록 범위(하드 리밋)는 더 넓고 따로 있다.
 */
@ConfigurationProperties(prefix = "app.control")
public record ControlProperties(List<SetpointSpec> setpoints, Duration commandTimeout, Duration freshness) {

    public ControlProperties {
        setpoints = setpoints == null ? List.of() : List.copyOf(setpoints);
        commandTimeout = commandTimeout == null ? Duration.ofSeconds(15) : commandTimeout;
        freshness = freshness == null ? Duration.ofSeconds(30) : freshness;
    }

    public Optional<SetpointSpec> find(String equipmentId, String tag) {
        return setpoints.stream()
                .filter(s -> s.equipmentId().equals(equipmentId) && s.tag().equals(tag))
                .findFirst();
    }

    /**
     * @param tag     PLC 태그 이름이자 텔레메트리 지표 이름 (예: speed_sp). 현재값은 최신 측정값에서 읽는다
     * @param maxStep 한 번에 바꿀 수 있는 최대 변경폭
     * @param nominal 평소 운전 기준값
     */
    public record SetpointSpec(String equipmentId, String tag, String label, String unit,
                               double min, double max, double maxStep, double nominal) {

        /** 제안값이 운전 범위 안인지 검사한다. 문제가 있으면 사유. */
        public Optional<String> check(Double current, double proposed) {
            if (current == null) {
                return Optional.of("설비의 현재 " + label + "을 읽을 수 없습니다 (가상 PLC · 게이트웨이 연결 확인)");
            }
            if (!Double.isFinite(proposed) || proposed < min || proposed > max) {
                return Optional.of(label + " 운전 범위 " + fmt(min) + "~" + fmt(max) + unit + " 밖입니다 (제안 "
                        + fmt(proposed) + unit + ")");
            }
            if (Math.abs(proposed - current) < 1e-9) {
                return Optional.of("현재 " + label + "과 같은 값입니다 (" + fmt(current) + unit + ")");
            }
            if (Math.abs(proposed - current) > maxStep + 1e-9) {
                return Optional.of(label + "은 한 번에 " + fmt(maxStep) + unit + "까지만 바꿀 수 있습니다 (현재 "
                        + fmt(current) + " → 제안 " + fmt(proposed) + ")");
            }
            return Optional.empty();
        }

        static String fmt(double v) {
            return v == Math.rint(v) ? String.valueOf((long) v) : String.valueOf(Math.round(v * 10) / 10.0);
        }
    }
}
