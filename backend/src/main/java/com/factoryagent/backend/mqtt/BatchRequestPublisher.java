package com.factoryagent.backend.mqtt;

import com.factoryagent.backend.mes.JobBatchRequestedEvent;
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
 * MES 배치 시작 요청을 설정값과 같은 명령 토픽으로 내려보낸다. 게이트웨이가 PLC 의 batchRequest 태그(Role CMD)에
 * "배치번호|레시피" 를 OPC UA 로 쓰고, PLC 인터록이 받아들이면 배치가 시작된다. 결과는 같은 결과 토픽으로 온다.
 */
@Component
public class BatchRequestPublisher {

    static final String TAG = "batchRequest";
    static final String CLEAN_TAG = "cleanRequest";
    private static final Logger log = LoggerFactory.getLogger(BatchRequestPublisher.class);

    private final MessageChannel outboundChannel;
    private final ObjectMapper objectMapper;
    private final String topic;

    public BatchRequestPublisher(@Qualifier("alarmOutboundChannel") MessageChannel outboundChannel,
                                 ObjectMapper objectMapper,
                                 @Value("${app.mqtt.command-topic}") String topic) {
        this.outboundChannel = outboundChannel;
        this.objectMapper = objectMapper;
        this.topic = topic;
    }

    /** 세정(CIP) 요청: 같은 명령 경로로 PLC 의 cleanRequest 태그에 세정 번호를 쓴다. */
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onClean(com.factoryagent.backend.mes.CleanRequestedEvent e) {
        try {
            String json = objectMapper.writeValueAsString(Map.of(
                    "requestId", e.requestId(),
                    "equipmentId", e.equipmentId(),
                    "tag", CLEAN_TAG,
                    "value", e.cipId(),
                    "approvedBy", e.worker()));
            outboundChannel.send(MessageBuilder.withPayload(json).setHeader(MqttHeaders.TOPIC, topic).build());
            log.info("[MES] clean request {} sent to {}", e.cipId(), topic);
        } catch (Exception ex) {
            log.warn("failed to publish clean request {}: {}", e.cipId(), ex.getMessage());
        }
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onRequested(JobBatchRequestedEvent e) {
        try {
            String json = objectMapper.writeValueAsString(Map.of(
                    "requestId", e.requestId(),
                    "equipmentId", e.equipmentId(),
                    "tag", TAG,
                    "value", e.batchId() + "|" + e.recipe(),
                    "approvedBy", e.worker()));
            outboundChannel.send(MessageBuilder.withPayload(json).setHeader(MqttHeaders.TOPIC, topic).build());
            log.info("[MES] batch request {} sent to {}", e.batchId(), topic);
        } catch (Exception ex) {
            log.warn("failed to publish batch request {}: {}", e.batchId(), ex.getMessage());
        }
    }
}
