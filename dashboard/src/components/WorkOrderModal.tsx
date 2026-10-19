import { useCallback, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import type { WorkOrder, WorkOrderStatus } from '../api'
import { formatTime } from '../format'
import { StatusBadge } from './StatusBadge'
import { ACTION_SECTION_ID, WorkOrderAction } from './WorkOrderAction'

const JUMP_LABEL: Record<WorkOrderStatus, string> = {
  OPEN: '지시서 확인',
  ACKNOWLEDGED: '조치 결과 입력',
  COMPLETED: '조치 결과',
  SUPERSEDED: '처리 내역',
}

interface Props {
  workOrder: WorkOrder
  onUpdated: (wo: WorkOrder) => void
  onClose: () => void
}

export function WorkOrderModal({ workOrder, onUpdated, onClose }: Props) {
  // 조치 내용을 쓰다가 Esc·바깥 클릭으로 닫혀 입력이 사라지지 않게 한 번 묻는다
  const dirtyRef = useRef(false)
  const onDirtyChange = useCallback((dirty: boolean) => {
    dirtyRef.current = dirty
  }, [])
  const requestClose = useCallback(() => {
    if (dirtyRef.current && !window.confirm('입력 중인 조치 내용이 저장되지 않았습니다. 닫을까요?')) return
    onClose()
  }, [onClose])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && requestClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [requestClose])

  const jumpToAction = () =>
    document.getElementById(ACTION_SECTION_ID)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  // 본문 첫 줄의 제목(# ...)과 '참고 문서' 목록은 모달 헤더·하단 표에서 따로 보여 준다
  const body = workOrder.body.replace(/^# .*\n/, '').replace(/\n## 참고 문서[\s\S]*$/, '')

  return (
    <div className="modal-backdrop" onClick={requestClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="wo-title" onClick={(e) => e.stopPropagation()}>
        <header className="modal__head">
          <div>
            <div className="modal__badges">
              <StatusBadge status={workOrder.severity} />
              <span className="muted">
                WO-{workOrder.id} · 알람 #{workOrder.alarmId} · {formatTime(workOrder.createdAt)}
              </span>
            </div>
            <h2 id="wo-title">{workOrder.title}</h2>
          </div>
          <div className="modal__actions">
            <button className="link-button" onClick={jumpToAction}>
              {JUMP_LABEL[workOrder.status]} ↓
            </button>
            <button className="icon-button" onClick={requestClose} aria-label="닫기">
              ✕
            </button>
          </div>
        </header>
        <div className="modal__body markdown">
          <ReactMarkdown>{body}</ReactMarkdown>
          <h2>근거 문서 (RAG 검색 결과)</h2>
          <table className="table">
            <thead>
              <tr>
                <th>매뉴얼</th>
                <th>섹션</th>
                <th className="num">점수</th>
              </tr>
            </thead>
            <tbody>
              {workOrder.references.map((r) => (
                <tr key={`${r.manualId}/${r.section}`}>
                  <td>
                    <b>{r.manualId}</b>
                    <div className="muted">{r.title}</div>
                  </td>
                  <td>{r.section}</td>
                  <td className="num">{r.score.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <WorkOrderAction workOrder={workOrder} onUpdated={onUpdated} onDirtyChange={onDirtyChange} />
        </div>
      </div>
    </div>
  )
}
