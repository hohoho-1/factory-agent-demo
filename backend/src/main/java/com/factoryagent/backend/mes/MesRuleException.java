package com.factoryagent.backend.mes;

/**
 * 현장 규칙에 걸려 배치를 시작할 수 없다. code 로 화면이 다음 행동을 고른다.
 * CHANGEOVER_REQUIRED(세정 필요) · CLEARANCE_REQUIRED(클리어런스 확인 필요) · SUPERVISOR_REQUIRED(책임자 승인 필요)
 */
public class MesRuleException extends RuntimeException {

    private final String code;

    public MesRuleException(String code, String message) {
        super(message);
        this.code = code;
    }

    public String getCode() {
        return code;
    }
}
