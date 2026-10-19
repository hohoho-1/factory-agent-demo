package com.factoryagent.backend.control;

import org.springframework.http.HttpStatus;

/** 설정값 변경을 받아들일 수 없음. 메시지는 작업자에게 그대로 보여 준다. */
public class SetpointException extends RuntimeException {

    private final HttpStatus status;

    public SetpointException(HttpStatus status, String message) {
        super(message);
        this.status = status;
    }

    public HttpStatus getStatus() {
        return status;
    }
}
