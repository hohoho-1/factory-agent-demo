import { useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import type { WorkOrder } from '../api'
import { formatTime } from '../format'
import { StatusBadge } from './StatusBadge'

interface Props {
  workOrder: WorkOrder
  onClose: () => void
}

export function WorkOrderModal({ workOrder, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // 본문 첫 줄의 제목(# ...)과 '참고 문서' 목록은 모달 헤더·하단 표에서 따로 보여 준다
  const body = workOrder.body.replace(/^# .*\n/, '').replace(/\n## 참고 문서[\s\S]*$/, '')

  return (
    <div className="modal-backdrop" onClick={onClose}>
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
          <button className="icon-button" onClick={onClose} aria-label="닫기">
            ✕
          </button>
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
        </div>
      </div>
    </div>
  )
}
