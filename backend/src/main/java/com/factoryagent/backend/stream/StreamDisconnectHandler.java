package com.factoryagent.backend.stream;

import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.io.IOException;

/**
 * 대시보드 탭을 닫거나 새로고침하면 SSE 연결이 끊긴 상태에서 다음 전송이 실패한다.
 * LiveStreamHub 가 해당 연결을 정리하지만, Spring 이 그 실패를 오류 디스패치로 넘기면
 * Tomcat 이 긴 스택 트레이스와 함께 ERROR 로 남긴다. 정상적인 연결 종료이므로 여기서 조용히 처리한다.
 */
@RestControllerAdvice
public class StreamDisconnectHandler {

    private static final Logger log = LoggerFactory.getLogger(StreamDisconnectHandler.class);

    @ExceptionHandler(IOException.class)
    public void onIoException(IOException e, HttpServletRequest request) throws IOException {
        if (!request.getRequestURI().startsWith("/api/stream")) {
            throw e; // SSE 가 아닌 요청의 I/O 오류는 그대로 드러낸다
        }
        log.debug("dashboard disconnected: {}", e.getMessage());
    }
}
