package com.factoryagent.backend.control;

import com.factoryagent.backend.telemetry.SensorReading;
import com.factoryagent.backend.telemetry.SensorReadingRepository;
import com.factoryagent.backend.workorder.WorkOrder;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.http.HttpStatus;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * 승인형 설정값 제어: AI 제안 → 작업자 승인/거절 → MQTT 명령 → 게이트웨이 OPC UA 쓰기 → 결과 보고.
 * 백엔드는 운전 범위를 제안·승인 때 두 번 검사하고, 모든 상태 변화를 감사 기록으로 남긴다.
 * 최종 안전장치는 PLC 안의 인터록이다 (백엔드가 통과시켜도 PLC 가 거부할 수 있다).
 */
@Service
public class SetpointService {

    private static final Logger log = LoggerFactory.getLogger(SetpointService.class);
    static final String GATEWAY_ACTOR = "PLC (게이트웨이 보고)";

    private final SetpointChangeRepository changes;
    private final SetpointAuditRepository audits;
    private final SensorReadingRepository readings;
    private final ControlProperties props;
    private final ApplicationEventPublisher events;

    public SetpointService(SetpointChangeRepository changes, SetpointAuditRepository audits,
                           SensorReadingRepository readings, ControlProperties props,
                           ApplicationEventPublisher events) {
        this.changes = changes;
        this.audits = audits;
        this.readings = readings;
        this.props = props;
        this.events = events;
    }

    /** 원격 설정값 1개와 현재값. 현재값은 게이트웨이가 올린 최신 측정값이고, 오래됐으면(연결 끊김) null. */
    public record SetpointView(String equipmentId, String tag, String label, String unit, double min, double max,
                               double maxStep, double nominal, Double currentValue, Instant measuredAt) {
    }

    /** 에이전트가 지시서와 함께 보내는 제안. 설비는 지시서의 설비. */
    public record ProposalRequest(String tag, Double proposedValue, String reason, String sources, String generator) {
    }

    @Transactional(readOnly = true)
    public List<SetpointView> setpoints(String equipmentId) {
        return props.setpoints().stream()
                .filter(s -> equipmentId == null || equipmentId.isBlank() || s.equipmentId().equals(equipmentId))
                .map(s -> {
                    Optional<SensorReading> r = freshReading(s);
                    return new SetpointView(s.equipmentId(), s.tag(), s.label(), s.unit(), s.min(), s.max(),
                            s.maxStep(), s.nominal(), r.map(SensorReading::getValue).orElse(null),
                            r.map(SensorReading::getMeasuredAt).orElse(null));
                })
                .toList();
    }

    @Transactional
    public SetpointChange propose(WorkOrder wo, ProposalRequest req) {
        if (req == null || req.tag() == null || req.proposedValue() == null) {
            throw new SetpointException(HttpStatus.BAD_REQUEST, "tag 와 proposedValue 가 필요합니다");
        }
        ControlProperties.SetpointSpec spec = spec(wo.getEquipmentId(), req.tag());
        Double current = freshReading(spec).map(SensorReading::getValue).orElse(null);
        spec.check(current, req.proposedValue()).ifPresent(reason -> {
            throw new SetpointException(HttpStatus.UNPROCESSABLE_ENTITY, reason);
        });
        Instant now = Instant.now();
        SetpointChange saved = changes.save(SetpointChange.propose(wo.getId(), wo.getAlarmId(), spec, current,
                req.proposedValue(), req.reason(), req.sources(), req.generator(), now));
        audit(saved, "PROPOSED", "AI (" + (req.generator() == null ? "unknown" : req.generator()) + ")",
                current, req.proposedValue(), "WO-" + wo.getId() + " " + nullToEmpty(req.reason()), now);
        log.info("[SETPOINT] #{} proposed for WO-{}: {}.{} {} -> {}", saved.getId(), wo.getId(),
                spec.equipmentId(), spec.tag(), current, req.proposedValue());
        events.publishEvent(new SetpointChangeEvent(saved));
        return saved;
    }

    /** 작업자 승인: 지금 현재값으로 다시 검사한 뒤 명령을 내려보낸다(커밋 후 MQTT). */
    @Transactional
    public SetpointChange approve(Long id, String worker) {
        SetpointChange c = find(id);
        requireProposed(c);
        ControlProperties.SetpointSpec spec = spec(c.getEquipmentId(), c.getTag());
        Double current = freshReading(spec).map(SensorReading::getValue).orElse(null);
        spec.check(current, c.getProposedValue()).ifPresent(reason -> {
            throw new SetpointException(HttpStatus.CONFLICT, "승인할 수 없습니다: " + reason);
        });
        Instant now = Instant.now();
        c.approve(worker, current, now);
        c = changes.save(c);
        audit(c, "APPROVED", worker, current, c.getProposedValue(), "명령 전송", now);
        log.info("[SETPOINT] #{} approved by {}: {}.{} {} -> {}", id, worker, c.getEquipmentId(), c.getTag(),
                current, c.getProposedValue());
        events.publishEvent(new SetpointChangeEvent(c));
        return c;
    }

    @Transactional
    public SetpointChange reject(Long id, String worker, String note) {
        SetpointChange c = find(id);
        requireProposed(c);
        Instant now = Instant.now();
        c.reject(worker, note == null || note.isBlank() ? null : note.trim(), now);
        c = changes.save(c);
        audit(c, "REJECTED", worker, c.getCurrentValue(), c.getProposedValue(), c.getDecisionNote(), now);
        log.info("[SETPOINT] #{} rejected by {}", id, worker);
        events.publishEvent(new SetpointChangeEvent(c));
        return c;
    }

    /** 게이트웨이 결과 보고. 백엔드가 보낸 명령이 아니면 외부 명령으로 새로 기록한다. */
    @Transactional
    public SetpointChange onResult(CommandResult r) {
        Instant now = Instant.now();
        SetpointChange c = r.requestId() == null ? null : changes.findById(r.requestId()).orElse(null);
        if (c == null) {
            Optional<ControlProperties.SetpointSpec> spec = props.find(r.equipmentId(), r.tag());
            c = changes.save(SetpointChange.external(r.equipmentId(), r.tag(),
                    spec.map(ControlProperties.SetpointSpec::label).orElse(r.tag()),
                    spec.map(ControlProperties.SetpointSpec::unit).orElse(null),
                    r.requested() == null ? Double.NaN : r.requested(), now));
            log.warn("[SETPOINT] external command on {}.{} (not approved here) -> {}", r.equipmentId(), r.tag(),
                    r.status());
        } else if (c.getStatus() != SetpointChange.Status.SENT) {
            audit(c, "LATE_RESULT", GATEWAY_ACTOR, r.before(), r.after(), r.status() + " " + r.message(), now);
            log.warn("[SETPOINT] #{} late result {} ignored (already {})", c.getId(), r.status(), c.getStatus());
            return c;
        }
        c.complete(r.toStatus(), r.before(), r.after(), r.code(), r.message(), now);
        c = changes.save(c);
        audit(c, c.getStatus().name(), c.getOrigin() == SetpointChange.Origin.EXTERNAL ? "외부 명령" : GATEWAY_ACTOR,
                r.before(), r.after(), r.code() + " " + nullToEmpty(r.message()), now);
        log.info("[SETPOINT] #{} {}: {}.{} {} -> {} ({})", c.getId(), c.getStatus(), c.getEquipmentId(), c.getTag(),
                r.before(), r.after(), r.message());
        events.publishEvent(new SetpointChangeEvent(c));
        return c;
    }

    /** 명령을 보냈는데 설비 응답이 없으면 실패로 닫는다 (게이트웨이가 꺼져 있는 경우 등). */
    @Scheduled(fixedDelay = 5_000)
    @Transactional
    public void expireUnanswered() {
        Instant now = Instant.now();
        for (SetpointChange c : changes.findByStatusAndDecidedAtBefore(SetpointChange.Status.SENT,
                now.minus(props.commandTimeout()))) {
            String message = "설비 응답 없음 (" + props.commandTimeout().toSeconds() + "초) — 게이트웨이 연결 확인";
            c.complete(SetpointChange.Status.FAILED, null, null, "Timeout", message, now);
            changes.save(c);
            audit(c, "FAILED", "시스템", c.getValueBefore(), null, message, now);
            log.warn("[SETPOINT] #{} failed: no response from gateway", c.getId());
            events.publishEvent(new SetpointChangeEvent(c));
        }
    }

    @Transactional(readOnly = true)
    public List<SetpointChange> recent() {
        return changes.findTop30ByOrderByCreatedAtDesc();
    }

    @Transactional(readOnly = true)
    public List<SetpointAudit> audit(Long id) {
        return audits.findByChangeIdOrderByAtAscIdAsc(id);
    }

    private Optional<SensorReading> freshReading(ControlProperties.SetpointSpec spec) {
        Instant oldest = Instant.now().minus(props.freshness());
        return readings.findFirstByEquipmentIdAndMetricOrderByMeasuredAtDesc(spec.equipmentId(), spec.tag())
                .filter(r -> r.getMeasuredAt().isAfter(oldest));
    }

    private ControlProperties.SetpointSpec spec(String equipmentId, String tag) {
        return props.find(equipmentId, tag).orElseThrow(() -> new SetpointException(HttpStatus.UNPROCESSABLE_ENTITY,
                equipmentId + "." + tag + " 는 원격으로 바꿀 수 있는 설정값이 아닙니다"));
    }

    private SetpointChange find(Long id) {
        return changes.findById(id).orElseThrow(() ->
                new SetpointException(HttpStatus.NOT_FOUND, "설정값 변경 #" + id + " 이 없습니다"));
    }

    private static void requireProposed(SetpointChange c) {
        if (c.getStatus() != SetpointChange.Status.PROPOSED) {
            throw new SetpointException(HttpStatus.CONFLICT, "이미 처리된 제안입니다 (" + c.getStatus() + ")");
        }
    }

    private void audit(SetpointChange c, String action, String actor, Double before, Double after,
                       String message, Instant at) {
        audits.save(SetpointAudit.of(c, action, actor, before, after, message, at));
    }

    private static String nullToEmpty(String s) {
        return s == null ? "" : s;
    }
}
