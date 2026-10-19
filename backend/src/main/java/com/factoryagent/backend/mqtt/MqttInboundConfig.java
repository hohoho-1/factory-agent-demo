package com.factoryagent.backend.mqtt;

import com.factoryagent.backend.control.CommandResult;
import com.factoryagent.backend.control.SetpointService;
import com.factoryagent.backend.telemetry.TelemetryService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.eclipse.paho.client.mqttv3.MqttConnectOptions;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.integration.dsl.IntegrationFlow;
import org.springframework.integration.mqtt.core.DefaultMqttPahoClientFactory;
import org.springframework.integration.mqtt.core.MqttPahoClientFactory;
import org.springframework.integration.mqtt.inbound.MqttPahoMessageDrivenChannelAdapter;
import org.springframework.integration.mqtt.support.DefaultPahoMessageConverter;
import org.springframework.integration.mqtt.support.MqttHeaders;

/**
 * OT → IT 연결 지점: MQTT 브로커의 텔레메트리 토픽을 구독해 TelemetryService 로 넘긴다.
 */
@Configuration
public class MqttInboundConfig {

    private static final Logger log = LoggerFactory.getLogger(MqttInboundConfig.class);

    @Bean
    public MqttPahoClientFactory mqttClientFactory(@Value("${app.mqtt.broker-url}") String brokerUrl) {
        MqttConnectOptions options = new MqttConnectOptions();
        options.setServerURIs(new String[]{brokerUrl});
        options.setAutomaticReconnect(true);
        options.setCleanSession(true);

        DefaultMqttPahoClientFactory factory = new DefaultMqttPahoClientFactory();
        factory.setConnectionOptions(options);
        return factory;
    }

    @Bean
    public IntegrationFlow telemetryInboundFlow(MqttPahoClientFactory clientFactory,
                                                TelemetryService telemetryService,
                                                @Value("${app.mqtt.client-id}") String clientId,
                                                @Value("${app.mqtt.topic}") String topic) {
        MqttPahoMessageDrivenChannelAdapter adapter =
                new MqttPahoMessageDrivenChannelAdapter(clientId, clientFactory, topic);
        adapter.setQos(0);
        adapter.setConverter(new DefaultPahoMessageConverter());

        return IntegrationFlow.from(adapter)
                .handle(String.class, (payload, headers) -> {
                    telemetryService.ingest((String) headers.get(MqttHeaders.RECEIVED_TOPIC), payload);
                    return null;
                })
                .get();
    }

    /** 게이트웨이가 보고하는 설정값 쓰기 결과 (반영 / 인터록 거부). */
    @Bean
    public IntegrationFlow commandResultInboundFlow(MqttPahoClientFactory clientFactory,
                                                   SetpointService setpointService,
                                                   ObjectMapper objectMapper,
                                                   @Value("${app.mqtt.client-id}") String clientId,
                                                   @Value("${app.mqtt.command-result-topic}") String topic) {
        MqttPahoMessageDrivenChannelAdapter adapter =
                new MqttPahoMessageDrivenChannelAdapter(clientId + "-results", clientFactory, topic);
        adapter.setQos(1);
        adapter.setConverter(new DefaultPahoMessageConverter());

        return IntegrationFlow.from(adapter)
                .handle(String.class, (payload, headers) -> {
                    try {
                        setpointService.onResult(objectMapper.readValue(payload, CommandResult.class));
                    } catch (Exception e) {
                        log.warn("invalid command result: {} ({})", payload, e.getMessage());
                    }
                    return null;
                })
                .get();
    }
}
