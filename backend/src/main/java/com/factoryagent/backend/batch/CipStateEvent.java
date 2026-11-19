package com.factoryagent.backend.batch;

/** 배합기 세정(CIP) 상태 태그가 바뀌었다. previousCipId 는 끝난 세정의 번호 (CLEANING → IDLE 일 때). */
public record CipStateEvent(String equipmentId, String previous, String current, String previousCipId,
                            java.time.Instant at) {
}
