package com.factoryagent.backend.quality;

/** 품질 판정 생성 · 품질팀 결정. 커밋 후 SSE 'quality' 로 대시보드에 보낸다. */
public record QualityAssessmentEvent(QualityAssessment assessment) {
}
