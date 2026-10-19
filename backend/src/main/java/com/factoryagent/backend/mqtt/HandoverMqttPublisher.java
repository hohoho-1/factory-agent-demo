package com.factoryagent.backend.mqtt;

import com.factoryagent.backend.handover.HandoverEvent;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.integration.mqtt.support.MqttHeaders;
import org.springframework.integration.support.MessageBuilder;
import org.springframework.messaging.MessageChannel;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

import java.util.Map;

/**
 * 인수인계 리포트 요청을 factory/line1/handover/requests 로 발행한다. 에이전트가 구독해 작성한다.
 * 알람과 같은 MQTT 발행 채널을 쓰고 토픽만 헤더로 바꾼다.
 */
@Component
public class HandoverMqttPublisher {

    private static final Logger log = LoggerFactory.getLogger(HandoverMqttPublisher.class);

    private final MessageChannel outboundChannel;
    private final ObjectMapper objectMapper;
    private final String topic;

    public HandoverMqttPublisher(@Qualifier("alarmOutboundChannel") MessageChannel outboundChannel,
                                 ObjectMapper objectMapper,
                                 @Value("${app.mqtt.handover-topic}") String topic) {
        this.outboundChannel = outboundChannel;
        this.objectMapper = objectMapper;
        this.topic = topic;
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onHandover(HandoverEvent event) {
        if (event.type() != HandoverEvent.Type.REQUESTED) {
            return;
        }
        try {
            String json = objectMapper.writeValueAsString(Map.of(
                    "reportId", event.report().getId(),
                    "from", event.report().getWindowFrom(),
                    "to", event.report().getWindowTo()));
            outboundChannel.send(MessageBuilder.withPayload(json).setHeader(MqttHeaders.TOPIC, topic).build());
        } catch (Exception e) {
            log.warn("failed to publish handover request #{}: {}", event.report().getId(), e.getMessage());
        }
    }
}
