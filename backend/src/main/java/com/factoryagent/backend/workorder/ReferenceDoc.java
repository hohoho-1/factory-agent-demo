package com.factoryagent.backend.workorder;

/** 조치 지시서 작성 근거가 된 매뉴얼 구절 (RAG 검색 결과). */
public record ReferenceDoc(String manualId, String title, String section, double score) {
}
