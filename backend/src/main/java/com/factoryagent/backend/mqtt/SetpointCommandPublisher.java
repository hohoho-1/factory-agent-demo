package com.factoryagent.backend.mqtt;

import com.factoryagent.backend.control.SetpointChange;
import com.factoryagent.backend.control.SetpointChangeEvent;
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
 * 승인된 설정값 변경을 factory/line1/commands 로 내려보낸다. 엣지 게이트웨이가 받아 PLC 에 OPC UA 로 쓴다.
 * 승인이 커밋된 뒤에만 보낸다 (감사 기록 없이 설비가 바뀌는 일이 없게).
 */
@Component
public class SetpointCommandPublisher {

    private static final Logger log = LoggerFactory.getLogger(SetpointCommandPublisher.class);

    private final MessageChannel outboundChannel;
    private final ObjectMapper objectMapper;
    private final String topic;

    public SetpointCommandPublisher(@Qualifier("alarmOutboundChannel") MessageChannel outboundChannel,
                                    ObjectMapper objectMapper,
                                    @Value("${app.mqtt.command-topic}") String topic) {
        this.outboundChannel = outboundChannel;
        this.objectMapper = objectMapper;
        this.topic = topic;
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onSetpoint(SetpointChangeEvent event) {
        if (!event.isCommand()) {
            return;
        }
        SetpointChange c = event.change();
        try {
            String json = objectMapper.writeValueAsString(Map.of(
                    "requestId", c.getId(),
                    "equipmentId", c.getEquipmentId(),
                    "tag", c.getTag(),
                    "value", c.getProposedValue(),
                    "approvedBy", c.getDecidedBy()));
            outboundChannel.send(MessageBuilder.withPayload(json).setHeader(MqttHeaders.TOPIC, topic).build());
            log.info("[SETPOINT] #{} command sent to {}", c.getId(), topic);
        } catch (Exception e) {
            // 보내지 못하면 응답이 없으므로 SetpointService 가 시간 초과로 FAILED 처리한다
            log.warn("failed to publish setpoint command #{}: {}", c.getId(), e.getMessage());
        }
    }
}
