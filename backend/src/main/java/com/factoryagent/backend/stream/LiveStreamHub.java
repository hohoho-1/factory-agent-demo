package com.factoryagent.backend.stream;

import com.factoryagent.backend.alarm.AlarmEvent;
import com.factoryagent.backend.handover.HandoverEvent;
import com.factoryagent.backend.telemetry.ReadingsSavedEvent;
import com.factoryagent.backend.workorder.WorkOrderCreatedEvent;
import com.factoryagent.backend.workorder.WorkOrderUpdatedEvent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * 대시보드로 실시간 이벤트를 밀어주는 SSE 허브.
 * 이벤트 이름: readings / alarm / work-order / handover / ping
 * 모두 커밋 이후에 보내 화면이 DB 와 어긋나지 않게 한다.
 */
@Component
public class LiveStreamHub {

    private static final Logger log = LoggerFactory.getLogger(LiveStreamHub.class);
    private static final long TIMEOUT_MS = 30 * 60 * 1000L; // 끊기면 브라우저 EventSource 가 자동 재연결

    private final List<SseEmitter> emitters = new CopyOnWriteArrayList<>();

    public SseEmitter subscribe() {
        SseEmitter emitter = new SseEmitter(TIMEOUT_MS);
        emitter.onCompletion(() -> emitters.remove(emitter));
        emitter.onTimeout(() -> emitters.remove(emitter));
        emitter.onError(e -> emitters.remove(emitter));
        emitters.add(emitter);
        send(emitter, "ping", Map.of("clients", emitters.size()));
        log.info("dashboard connected (clients={})", emitters.size());
        return emitter;
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onReadings(ReadingsSavedEvent e) {
        broadcast("readings", e.readings());
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onAlarm(AlarmEvent e) {
        broadcast("alarm", Map.of("event", e.event(), "alarm", e.alarm()));
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onWorkOrder(WorkOrderCreatedEvent e) {
        broadcast("work-order", e.workOrder());
    }

    /** 인수인계 리포트 요청·작성 완료. 화면은 id 로 덮어쓴다. */
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onHandover(HandoverEvent e) {
        broadcast("handover", e.report());
    }

    /** 확인·조치 완료도 같은 이벤트로 보낸다. 화면은 id 로 덮어쓴다. */
    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onWorkOrderUpdated(WorkOrderUpdatedEvent e) {
        broadcast("work-order", e.workOrder());
    }

    /** 프록시·브라우저가 유휴 연결을 끊지 않도록 주기적으로 신호를 보낸다. */
    @Scheduled(fixedRate = 15_000)
    public void heartbeat() {
        broadcast("ping", Map.of("clients", emitters.size()));
    }

    private void broadcast(String name, Object data) {
        for (SseEmitter emitter : emitters) {
            send(emitter, name, data);
        }
    }

    private void send(SseEmitter emitter, String name, Object data) {
        // SseEmitter 는 동시 send 에 안전하지 않다 (MQTT 스레드, 스케줄러, 요청 스레드가 함께 보냄)
        synchronized (emitter) {
            try {
                emitter.send(SseEmitter.event().name(name).data(data, MediaType.APPLICATION_JSON));
            } catch (IOException | IllegalStateException ex) {
                // 브라우저가 떠난 연결. 이후 Spring 이 넘기는 오류는 StreamDisconnectHandler 가 정리한다
                if (emitters.remove(emitter)) {
                    log.info("dashboard disconnected (clients={})", emitters.size());
                }
            }
        }
    }
}
