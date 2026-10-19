package com.factoryagent.backend.forecast;

/**
 * 예측 경보 변화. CLEARED 의 reason: ALARM(실제 알람이 발생) / RECOVERED(추세가 꺾임).
 * ALARM 이면 leadSeconds 에 '예측이 실제 알람보다 몇 초 먼저였는지'를 담는다.
 */
public record ForecastEvent(Type type, Forecast forecast, String reason, Long leadSeconds) {

    public enum Type { RAISED, UPDATED, CLEARED }
}
