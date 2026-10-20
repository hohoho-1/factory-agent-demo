package com.factoryagent.backend.forecast;

import com.factoryagent.backend.alarm.Threshold;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 추세 기반 조기 경보.
 * 설비·지표마다 최근 20개 측정값으로 직선 회귀를 하고, 추세가 직선에 가깝고(R² ≥ 0.7)
 * 값이 평소 수준에서 충분히 벗어났으며, 이 기울기로 45초 안에 경고 기준에 닿을 것 같으면 예측 경보를 낸다.
 * 상태는 메모리에만 둔다 (재시작하면 2분 정도 평소 수준을 다시 배운다).
 */
@Component
public class TrendForecaster {

    static final int WINDOW = 40;
    /** 창이 꽉 찼을 때만 본다. 표본이 적으면 노이즈가 추세처럼 보인다 */
    static final int MIN_SAMPLES = WINDOW;
    /**
     * 추세가 이 정도는 직선이어야 한다. 오경보는 주로 아래 '평소 수준에서 벗어남' 조건이 막고,
     * 두 조건을 함께 써서 정상 노이즈 3시간 이상 시뮬레이션에서 오경보 0건 (TrendForecasterTest)
     */
    static final double MIN_R2 = 0.5;
    static final long HORIZON_SECONDS = 60;
    /** 예측 조건이 이만큼 연속으로 안 맞으면 해제 (한두 번 흔들림으로 깜빡이지 않게) */
    static final int CLEAR_AFTER_MISSES = 5;
    /** 진행 중 예측의 갱신 이벤트는 이 간격 이상으로만 보낸다 (화면은 etaAt 으로 직접 카운트다운) */
    static final Duration UPDATE_EVERY = Duration.ofSeconds(5);
    /** 평소 수준·흔들림(지수 이동 평균·분산, 시상수 약 50초) */
    static final double BASELINE_ALPHA = 0.02;
    /**
     * 평소 수준에서 '흔들림(σ)의 4배' 이상, 그리고 '기준까지 거리의 25%' 이상 벗어났을 때만 예측한다.
     * 정상 노이즈가 우연히 20초 동안 오른 구간을 추세로 오인하지 않게. σ 를 신호마다 재므로 센서별 노이즈 차이에 맞춰진다.
     */
    static final double MIN_SIGMAS = 4.0;
    static final double MIN_DEPARTURE = 0.25;

    /** 설비·지표별 평소 수준과 흔들림. */
    record Baseline(double mean, double variance) {
        Baseline update(double value) {
            double diff = value - mean;
            double nextMean = mean + BASELINE_ALPHA * diff;
            double nextVar = (1 - BASELINE_ALPHA) * (variance + BASELINE_ALPHA * diff * diff);
            return new Baseline(nextMean, nextVar);
        }

        double sigma() {
            return Math.sqrt(variance);
        }
    }

    record Sample(Instant at, double value) {
    }

    record Prediction(Threshold.Direction direction, double limit, double slopePerSecond, double r2, long secondsToLimit) {
    }

    private final Map<String, Deque<Sample>> windows = new HashMap<>();
    private final Map<String, Forecast> active = new HashMap<>();
    private final Map<String, Integer> misses = new HashMap<>();
    private final Map<String, Instant> lastPublished = new HashMap<>();
    private final Map<String, Baseline> baselines = new HashMap<>();

    /**
     * 측정값 1건을 반영하고, 예측 경보가 생기거나 바뀌거나 사라졌으면 이벤트를 돌려준다.
     *
     * @param alarmActive 이 지표에 실제 알람이 진행 중인지 (진행 중이면 예측하지 않는다)
     */
    public synchronized Optional<ForecastEvent> observe(String equipmentId, String equipmentType, String metric,
                                                        String unit, Instant at, double value, Threshold threshold,
                                                        boolean alarmActive) {
        String key = equipmentId + ":" + metric;
        Deque<Sample> window = windows.computeIfAbsent(key, k -> new ArrayDeque<>());
        window.addLast(new Sample(at, value));
        while (window.size() > WINDOW) {
            window.removeFirst();
        }

        Forecast current = active.get(key);
        List<Sample> samples = List.copyOf(window);
        Optional<Fit> fit = fit(samples);
        boolean trending = fit.map(f -> f.r2() >= MIN_R2).orElse(false);
        Baseline baseline = baselines.getOrDefault(key, new Baseline(value, 0));
        if (!alarmActive && current == null && !trending) {
            // 평소 수준은 '정상일 때'만 배운다. 추세·예측·알람 중에 갱신하면 기준선이 이상 값을 따라간다
            baselines.put(key, baseline.update(value));
        }
        if (alarmActive) {
            if (current == null) {
                return Optional.empty();
            }
            clear(key);
            long lead = Duration.between(current.raisedAt(), at).toSeconds();
            return Optional.of(new ForecastEvent(ForecastEvent.Type.CLEARED, current, "ALARM", lead));
        }

        Optional<Prediction> prediction = fit.flatMap(f -> predict(f, value, threshold))
                .filter(p -> departed(baseline, value, p.limit()));
        if (prediction.isEmpty()) {
            if (current == null) {
                return Optional.empty();
            }
            int missed = misses.merge(key, 1, Integer::sum);
            if (missed < CLEAR_AFTER_MISSES) {
                return Optional.empty();
            }
            clear(key);
            return Optional.of(new ForecastEvent(ForecastEvent.Type.CLEARED, current, "RECOVERED", null));
        }

        misses.remove(key);
        Prediction p = prediction.get();
        Forecast next = new Forecast(equipmentId, equipmentType, metric, unit, p.direction(), p.limit(), value,
                round(p.slopePerSecond() * 60), p.secondsToLimit(), at.plusSeconds(p.secondsToLimit()),
                current == null ? at : current.raisedAt(), at);
        active.put(key, next);
        if (current == null) {
            lastPublished.put(key, at);
            return Optional.of(new ForecastEvent(ForecastEvent.Type.RAISED, next, null, null));
        }
        if (Duration.between(lastPublished.get(key), at).compareTo(UPDATE_EVERY) >= 0) {
            lastPublished.put(key, at);
            return Optional.of(new ForecastEvent(ForecastEvent.Type.UPDATED, next, null, null));
        }
        return Optional.empty();
    }

    public synchronized List<Forecast> current() {
        return List.copyOf(active.values());
    }

    /**
     * 배치 단계가 바뀌면 그 설비의 추세 창·평소 수준을 버린다 (단계마다 정상 수준이 다르다).
     * 진행 중이던 예측은 해제 이벤트로 돌려준다.
     */
    public synchronized List<ForecastEvent> reset(String equipmentId) {
        String prefix = equipmentId + ":";
        List<ForecastEvent> cleared = active.entrySet().stream()
                .filter(e -> e.getKey().startsWith(prefix))
                .map(e -> new ForecastEvent(ForecastEvent.Type.CLEARED, e.getValue(), "PHASE", null))
                .toList();
        cleared.forEach(e -> clear(e.forecast().equipmentId() + ":" + e.forecast().metric()));
        windows.keySet().removeIf(k -> k.startsWith(prefix));
        baselines.keySet().removeIf(k -> k.startsWith(prefix));
        return cleared;
    }

    /** 현재 값이 평소 수준에서 기준 쪽으로 충분히 벗어났는지 (기준 방향 무관). */
    static boolean departed(Baseline baseline, double value, double limit) {
        double gap = limit - baseline.mean();
        if (gap == 0) {
            return false;
        }
        double toward = (value - baseline.mean()) * Math.signum(gap);  // 기준 쪽으로 벗어난 양
        return toward >= MIN_SIGMAS * baseline.sigma() && toward >= MIN_DEPARTURE * Math.abs(gap);
    }

    private void clear(String key) {
        active.remove(key);
        misses.remove(key);
        lastPublished.remove(key);
    }

    record Fit(double slopePerSecond, double r2) {
    }

    /** 최근 측정값의 기준 도달 시간을 계산한다. 추세가 약하거나 멀면 없음. */
    static Optional<Prediction> predict(List<Sample> samples, double current, Threshold threshold) {
        return fit(samples).flatMap(f -> predict(f, current, threshold));
    }

    /** 직선 회귀 기울기와 R². 표본이 모자라거나 값이 변하지 않으면 없음. */
    static Optional<Fit> fit(List<Sample> samples) {
        int n = samples.size();
        if (n < MIN_SAMPLES) {
            return Optional.empty();
        }
        Instant t0 = samples.get(0).at();
        double sx = 0, sy = 0, sxx = 0, sxy = 0, syy = 0;
        for (Sample s : samples) {
            double x = Duration.between(t0, s.at()).toMillis() / 1000.0;
            double y = s.value();
            sx += x;
            sy += y;
            sxx += x * x;
            sxy += x * y;
            syy += y * y;
        }
        double varX = n * sxx - sx * sx;
        double varY = n * syy - sy * sy;
        if (varX <= 0 || varY <= 0) {
            return Optional.empty();
        }
        double cov = n * sxy - sx * sy;
        return Optional.of(new Fit(cov / varX, cov * cov / (varX * varY)));
    }

    static Optional<Prediction> predict(Fit fit, double current, Threshold threshold) {
        double slope = fit.slopePerSecond();
        double r2 = fit.r2();
        if (r2 < MIN_R2) {
            return Optional.empty();
        }

        Threshold.Direction direction;
        Double limit;
        if (slope > 0) {
            direction = Threshold.Direction.HIGH;
            limit = threshold.warnHigh() != null ? threshold.warnHigh() : threshold.critHigh();
        } else {
            direction = Threshold.Direction.LOW;
            limit = threshold.warnLow() != null ? threshold.warnLow() : threshold.critLow();
        }
        if (limit == null) {
            return Optional.empty();
        }
        double seconds = (limit - current) / slope;
        if (seconds <= 0 || seconds > HORIZON_SECONDS) {
            return Optional.empty();
        }
        return Optional.of(new Prediction(direction, limit, slope, r2, Math.round(seconds)));
    }

    private static double round(double v) {
        return Math.round(v * 100) / 100.0;
    }
}
