package com.factoryagent.backend.alarm;

/** 알람 상태 변화. 트랜잭션 커밋 후 MQTT 로 내보낸다 (AlarmMqttPublisher). */
public record AlarmEvent(Type event, Alarm alarm) {

    public enum Type {
        RAISED,
        ESCALATED,
        CLEARED
    }
}
