package com.factoryagent.backend.mqtt;

import com.factoryagent.backend.assistant.AssistantEvent;
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

/** AI 작업 요청을 factory/line1/assistant/requests 로 발행한다. 에이전트가 구독해 작성한다. */
@Component
public class AssistantMqttPublisher {

    private static final Logger log = LoggerFactory.getLogger(AssistantMqttPublisher.class);

    private final MessageChannel outboundChannel;
    private final ObjectMapper objectMapper;
    private final String topic;

    public AssistantMqttPublisher(@Qualifier("alarmOutboundChannel") MessageChannel outboundChannel,
                                  ObjectMapper objectMapper,
                                  @Value("${app.mqtt.assistant-topic}") String topic) {
        this.outboundChannel = outboundChannel;
        this.objectMapper = objectMapper;
        this.topic = topic;
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onAssistant(AssistantEvent event) {
        if (event.type() != AssistantEvent.Type.REQUESTED) {
            return;
        }
        try {
            String json = objectMapper.writeValueAsString(Map.of(
                    "taskId", event.task().getId(),
                    "type", event.task().getType()));
            outboundChannel.send(MessageBuilder.withPayload(json).setHeader(MqttHeaders.TOPIC, topic).build());
        } catch (Exception e) {
            log.warn("failed to publish assistant task #{}: {}", event.task().getId(), e.getMessage());
        }
    }
}
