package com.factoryagent.backend.mqtt;

import com.factoryagent.backend.alarm.AlarmEvent;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.integration.support.MessageBuilder;
import org.springframework.messaging.MessageChannel;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

import java.util.Map;

/**
 * 알람 상태 변화를 factory/line1/alarms 로 발행한다.
 * 커밋 후에 보내야 에이전트가 조치 지시서를 저장할 때 알람 행이 이미 존재한다.
 */
@Component
public class AlarmMqttPublisher {

    private static final Logger log = LoggerFactory.getLogger(AlarmMqttPublisher.class);

    private final MessageChannel alarmOutboundChannel;
    private final ObjectMapper objectMapper;

    public AlarmMqttPublisher(@Qualifier("alarmOutboundChannel") MessageChannel alarmOutboundChannel,
                              ObjectMapper objectMapper) {
        this.alarmOutboundChannel = alarmOutboundChannel;
        this.objectMapper = objectMapper;
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
    public void onAlarm(AlarmEvent event) {
        try {
            String json = objectMapper.writeValueAsString(
                    Map.of("event", event.event(), "alarm", event.alarm()));
            alarmOutboundChannel.send(MessageBuilder.withPayload(json).build());
        } catch (Exception e) {
            // 발행 실패가 센서 수집을 막으면 안 된다
            log.warn("failed to publish alarm #{} {}: {}", event.alarm().getId(), event.event(), e.getMessage());
        }
    }
}
