package com.factoryagent.backend.mqtt;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.integration.channel.DirectChannel;
import org.springframework.integration.dsl.IntegrationFlow;
import org.springframework.integration.mqtt.core.MqttPahoClientFactory;
import org.springframework.integration.mqtt.outbound.MqttPahoMessageHandler;
import org.springframework.messaging.MessageChannel;

/**
 * IT → 에이전트 방향: 알람 이벤트를 MQTT 로 발행한다. Python AI 에이전트가 구독한다.
 */
@Configuration
public class MqttOutboundConfig {

    @Bean
    public MessageChannel alarmOutboundChannel() {
        return new DirectChannel();
    }

    @Bean
    public IntegrationFlow alarmOutboundFlow(MqttPahoClientFactory clientFactory,
                                             @Value("${app.mqtt.client-id}") String clientId,
                                             @Value("${app.mqtt.alarm-topic}") String alarmTopic) {
        MqttPahoMessageHandler handler = new MqttPahoMessageHandler(clientId + "-pub", clientFactory);
        handler.setAsync(true);
        handler.setDefaultTopic(alarmTopic);
        handler.setDefaultQos(1);

        return IntegrationFlow.from(alarmOutboundChannel())
                .handle(handler)
                .get();
    }
}
