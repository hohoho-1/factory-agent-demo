package com.factoryagent.backend.alarm;

/** 알람 억제 시작·해제. 커밋 후 SSE 'shelf' 로 대시보드에 보낸다 (화면은 id 로 덮어쓴다). */
public record AlarmShelfEvent(AlarmShelf shelf) {
}
