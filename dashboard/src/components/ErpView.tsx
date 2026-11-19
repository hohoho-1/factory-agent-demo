import { useCallback, useEffect, useState } from 'react'
import { getJson, postJson } from '../api'

/**
 * ERP · 경영 화면. 가상 ERP 서비스(:8090, /erp)를 읽는다. 현장 관제 화면(백엔드 :8080)과 시스템이 다르다:
 * 화면은 하나, 시스템은 둘. 생산 오더는 '현장 지시'로 MES 에 내려가고, 배치 실적이 올라오면 재고가 바뀐다.
 */

interface Summary {
  openOrders: number
  unplannedOrders: number
  atRiskOrders: number
  openOrderQty: number
  inventoryValue: number
  belowSafety: string[]
  openPurchaseAmount: number
  openPurchases: number
}

interface SalesOrder {
  id: number
  orderNo: string
  customer: string
  itemCode: string
  itemName: string
  qty: number
  dueDate: string
  status: 'OPEN' | 'PLANNED' | 'IN_PRODUCTION' | 'COMPLETED' | 'SHIPPED'
  productionNo: string | null
  plannedEnd: string | null
  atRisk: boolean
  riskReason: string | null
}

interface Material {
  itemCode: string
  required: number
  allocated: number
  shortage: number
}

interface ProductionOrder {
  id: number
  orderNo: string
  salesNo: string | null
  customer: string | null
  itemCode: string
  itemName: string
  qty: number
  batches: number
  materialReady: string
  plannedStart: string
  plannedEnd: string
  dueDate: string | null
  atRisk: boolean
  riskReason: string | null
  plannedCost: number
  status: 'PLANNED' | 'RELEASED' | 'IN_PROGRESS' | 'COMPLETED' | 'ON_HOLD'
  producedQty: number
  batchesDone: number
  materials: Material[]
}

const PO_STATUS: Record<ProductionOrder['status'], string> = {
  PLANNED: '계획',
  RELEASED: '현장 지시됨',
  IN_PROGRESS: '생산 중',
  COMPLETED: '생산 완료',
  ON_HOLD: '보류',
}

interface PurchaseOrder {
  id: number
  orderNo: string
  itemCode: string
  itemName: string
  uom: string
  qty: number
  amount: number
  expectedDate: string
  status: 'OPEN' | 'RECEIVED'
  productionNo: string | null
}

interface Stock {
  code: string
  name: string
  type: 'FG' | 'RM' | 'PM'
  uom: string
  onHand: number
  allocated: number
  available: number
  safetyStock: number
  value: number
  belowSafety: boolean
}

interface Cost {
  itemCode: string
  name: string
  material: number
  conversion: number
  total: number
  lines: { itemCode: string; name: string; qty: number; uom: string; unitCost: number; amount: number }[]
}

const SO_STATUS: Record<SalesOrder['status'], string> = {
  OPEN: '계획 전',
  PLANNED: '생산 계획됨',
  IN_PRODUCTION: '생산 중',
  COMPLETED: '생산 완료',
  SHIPPED: '출하',
}

const PRODUCTS = [
  { code: 'CAP-A30', name: '캡슐 세제 A 30개입' },
  { code: 'CAP-B15', name: '캡슐 세제 B 15개입' },
]

const won = (v: number) => `${Math.round(v).toLocaleString('ko-KR')}원`
const qty = (v: number) => (Number.isInteger(v) ? v.toLocaleString('ko-KR') : v.toLocaleString('ko-KR', { maximumFractionDigits: 2 }))
const day = (iso: string | null) => (iso ? iso.slice(5).replace('-', '/') : '—')

function addDays(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

export function ErpView() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [orders, setOrders] = useState<SalesOrder[]>([])
  const [production, setProduction] = useState<ProductionOrder[]>([])
  const [purchases, setPurchases] = useState<PurchaseOrder[]>([])
  const [stock, setStock] = useState<Stock[]>([])
  const [costs, setCosts] = useState<Cost[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [form, setForm] = useState({ customer: '', itemCode: 'CAP-A30', qty: '30000', dueDate: addDays(6) })

  const load = useCallback(async () => {
    try {
      const [s, so, pr, pu, st, ...cs] = await Promise.all([
        getJson<Summary>('/erp/summary'),
        getJson<SalesOrder[]>('/erp/sales-orders'),
        getJson<ProductionOrder[]>('/erp/production-orders'),
        getJson<PurchaseOrder[]>('/erp/purchase-orders'),
        getJson<Stock[]>('/erp/inventory'),
        ...PRODUCTS.map((p) => getJson<Cost>(`/erp/items/${p.code}/cost`)),
      ])
      setSummary(s)
      setOrders(so)
      setProduction(pr)
      setPurchases(pu)
      setStock(st)
      setCosts(cs)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  // MES 가 배치 실적을 올리면 재고 · 진행률이 바뀌므로 주기적으로 다시 읽는다
  useEffect(() => {
    void load()
    const id = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(id)
  }, [load])

  const act = async (label: string, fn: () => Promise<string>) => {
    setBusy(true)
    setMessage(null)
    try {
      setMessage(await fn())
      await load()
    } catch (e) {
      setMessage(`${label} 실패: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const createOrder = (e: React.FormEvent) => {
    e.preventDefault()
    void act('주문 등록', async () => {
      const so = await postJson<SalesOrder>('/erp/sales-orders', {
        customer: form.customer.trim() || '신규 고객',
        itemCode: form.itemCode,
        qty: Number(form.qty),
        dueDate: form.dueDate,
      })
      return `${so.orderNo} 등록: ${so.itemName} ${qty(so.qty)}파우치, 납기 ${day(so.dueDate)}`
    })
  }

  const plan = (so: SalesOrder) =>
    act('생산 계획', async () => {
      const r = await postJson<{ productionOrder: ProductionOrder; purchaseOrders: PurchaseOrder[] }>(
        `/erp/sales-orders/${so.id}/plan`,
        {},
      )
      const p = r.productionOrder
      return (
        `${p.orderNo} 계획: ${day(p.plannedStart)}~${day(p.plannedEnd)}, 배합 ${p.batches}배치` +
        (r.purchaseOrders.length ? `, 부족 자재 발주 ${r.purchaseOrders.length}건` : ', 자재 충분') +
        (p.atRisk ? ` — 납기 위험: ${p.riskReason}` : '')
      )
    })

  const receive = (po: PurchaseOrder) =>
    act('입고', async () => {
      const r = await postJson<{ rescheduled: number[] }>(`/erp/purchase-orders/${po.id}/receive`, {})
      return `${po.orderNo} 입고: ${po.itemName} ${qty(po.qty)}${po.uom}` + (r.rescheduled.length ? ' · 생산 일정 다시 계산' : '')
    })

  const release = (p: ProductionOrder) =>
    act('현장 지시', async () => {
      await postJson(`/erp/production-orders/${p.id}/release`, {})
      return `${p.orderNo}를 현장(MES)에 지시했습니다. 현장 관제 화면의 '생산 지시'에서 배치를 시작하세요`
    })

  const reset = () =>
    act('초기화', async () => {
      await postJson('/erp/reset', {})
      return 'ERP 데이터를 기초 데이터로 되돌렸습니다'
    })

  if (error && !summary) {
    return (
      <main className="erp">
        <div className="error">
          가상 ERP 서비스(:8090)에 연결하지 못했습니다: {error}. 'demo: erp' 창이 떠 있는지 확인하세요.
        </div>
      </main>
    )
  }

  return (
    <main className="erp">
      <section className="erp__kpis" aria-label="경영 요약">
        <div className="erp__kpi">
          <span className="kpi__label">미결 주문</span>
          <b>{summary?.openOrders ?? '—'}</b>
          <span className="muted">{summary ? `${qty(summary.openOrderQty)}파우치` : ''}</span>
        </div>
        <div className="erp__kpi">
          <span className="kpi__label">계획 전 주문</span>
          <b>{summary?.unplannedOrders ?? '—'}</b>
        </div>
        <div className={`erp__kpi${summary?.atRiskOrders ? ' erp__kpi--risk' : ''}`}>
          <span className="kpi__label">납기 위험</span>
          <b>{summary?.atRiskOrders ?? '—'}</b>
        </div>
        <div className="erp__kpi">
          <span className="kpi__label">재고 금액</span>
          <b>{summary ? won(summary.inventoryValue) : '—'}</b>
          <span className="muted">{summary?.belowSafety.length ? `안전재고 미달 ${summary.belowSafety.length}종` : ''}</span>
        </div>
        <div className="erp__kpi">
          <span className="kpi__label">미입고 발주</span>
          <b>{summary ? won(summary.openPurchaseAmount) : '—'}</b>
          <span className="muted">{summary ? `${summary.openPurchases}건` : ''}</span>
        </div>
      </section>

      {message && <p className="erp__message">{message}</p>}

      <section className="card panel">
        <header className="panel__head">
          <h2>판매 주문</h2>
          <span className="count">{orders.length}</span>
        </header>
        <form className="erp__form" onSubmit={createOrder}>
          <input
            id="erp-customer"
            value={form.customer}
            onChange={(e) => setForm({ ...form, customer: e.target.value })}
            placeholder="고객 (예: 대형 유통사)"
            aria-label="고객"
          />
          <select
            id="erp-item"
            value={form.itemCode}
            onChange={(e) => setForm({ ...form, itemCode: e.target.value })}
            aria-label="품목"
          >
            {PRODUCTS.map((p) => (
              <option key={p.code} value={p.code}>
                {p.name}
              </option>
            ))}
          </select>
          <input
            id="erp-qty"
            type="number"
            min={1}
            value={form.qty}
            onChange={(e) => setForm({ ...form, qty: e.target.value })}
            aria-label="수량 (파우치)"
          />
          <input
            id="erp-due"
            type="date"
            value={form.dueDate}
            onChange={(e) => setForm({ ...form, dueDate: e.target.value })}
            aria-label="납기"
          />
          <button className="button" disabled={busy}>
            주문 등록
          </button>
        </form>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>주문</th>
                <th>고객</th>
                <th>품목</th>
                <th className="num">수량(파우치)</th>
                <th>납기</th>
                <th>상태</th>
                <th>생산 종료 예정</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {orders.map((so) => (
                <tr key={so.id} className={so.atRisk ? 'erp__row--risk' : undefined}>
                  <td>{so.orderNo}</td>
                  <td>{so.customer}</td>
                  <td>{so.itemName}</td>
                  <td className="num">{qty(so.qty)}</td>
                  <td>{day(so.dueDate)}</td>
                  <td>{SO_STATUS[so.status]}</td>
                  <td>
                    {so.productionNo ? `${so.productionNo} · ${day(so.plannedEnd)}` : '—'}
                    {so.atRisk && <div className="erp__risk">납기 위험: {so.riskReason}</div>}
                  </td>
                  <td>
                    {so.status === 'OPEN' && (
                      <button className="button button--ghost" disabled={busy} onClick={() => void plan(so)}>
                        생산 계획
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card panel">
        <header className="panel__head">
          <h2>생산 오더</h2>
          <span className="count">{production.length}</span>
          <span className="muted erp__hint">현장 지시 → MES 배치 → 배치마다 실적 · 원료 출고 · 완제품 입고</span>
        </header>
        {production.length === 0 ? (
          <p className="empty">판매 주문에서 "생산 계획"을 누르면 생산 오더가 생깁니다.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>생산 오더</th>
                  <th>주문</th>
                  <th>품목</th>
                  <th className="num">수량</th>
                  <th className="num">배합 배치</th>
                  <th>자재 확보</th>
                  <th>생산 일정</th>
                  <th>납기</th>
                  <th className="num">계획 원가</th>
                  <th>부족 자재</th>
                  <th>상태 · 실적</th>
                </tr>
              </thead>
              <tbody>
                {production.map((p) => {
                  const short = p.materials.filter((m) => m.shortage > 0)
                  return (
                    <tr key={p.id} className={p.atRisk ? 'erp__row--risk' : undefined}>
                      <td>{p.orderNo}</td>
                      <td>{p.salesNo ?? '—'}</td>
                      <td>{p.itemName}</td>
                      <td className="num">{qty(p.qty)}</td>
                      <td className="num">{p.batches}</td>
                      <td>{day(p.materialReady)}</td>
                      <td>
                        {day(p.plannedStart)} ~ {day(p.plannedEnd)}
                        {p.atRisk && <div className="erp__risk">{p.riskReason}</div>}
                      </td>
                      <td>{day(p.dueDate)}</td>
                      <td className="num">{won(p.plannedCost)}</td>
                      <td className="erp__wrap">
                        {short.length ? short.map((m) => `${m.itemCode} ${qty(m.shortage)}`).join(', ') : '없음'}
                      </td>
                      <td>
                        <div className="erp__status">
                          <span>{PO_STATUS[p.status]}</span>
                          {p.status === 'PLANNED' && (
                            <button
                              className="button button--ghost"
                              disabled={busy || short.length > 0}
                              title={short.length ? '부족 자재가 입고된 뒤 지시할 수 있습니다' : undefined}
                              onClick={() => void release(p)}
                            >
                              현장 지시
                            </button>
                          )}
                        </div>
                        {p.status !== 'PLANNED' && (
                          <div className="muted">
                            배치 {p.batchesDone}/{p.batches} · {qty(p.producedQty)}파우치
                          </div>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="erp__grid">
        <section className="card panel">
          <header className="panel__head">
            <h2>구매 발주</h2>
            <span className="count">{purchases.filter((p) => p.status === 'OPEN').length}</span>
          </header>
          {purchases.length === 0 ? (
            <p className="empty">자재가 모자라면 생산 계획 때 발주가 자동으로 생깁니다.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>발주</th>
                    <th>자재</th>
                    <th className="num">수량</th>
                    <th>입고 예정</th>
                    <th className="num">금액</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {purchases.map((po) => (
                    <tr key={po.id}>
                      <td>
                        {po.orderNo}
                        <div className="muted">{po.productionNo}</div>
                      </td>
                      <td>{po.itemName}</td>
                      <td className="num">
                        {qty(po.qty)} {po.uom}
                      </td>
                      <td>{day(po.expectedDate)}</td>
                      <td className="num">{won(po.amount)}</td>
                      <td>
                        {po.status === 'OPEN' ? (
                          <button className="button button--ghost" disabled={busy} onClick={() => void receive(po)}>
                            입고
                          </button>
                        ) : (
                          <span className="muted">입고됨</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="card panel">
          <header className="panel__head">
            <h2>재고</h2>
            <span className="muted erp__hint">가용 = 현재고 − 생산 오더 할당</span>
          </header>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>품목</th>
                  <th className="num">현재고</th>
                  <th className="num">할당</th>
                  <th className="num">가용</th>
                  <th className="num">안전재고</th>
                </tr>
              </thead>
              <tbody>
                {stock
                  .filter((s) => s.type !== 'FG')
                  .map((s) => (
                    <tr key={s.code} className={s.belowSafety ? 'erp__row--risk' : undefined}>
                      <td>
                        {s.name} <span className="muted">{s.code}</span>
                      </td>
                      <td className="num">
                        {qty(s.onHand)} {s.uom}
                      </td>
                      <td className="num">{qty(s.allocated)}</td>
                      <td className="num">{qty(s.available)}</td>
                      <td className="num">{qty(s.safetyStock)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section className="card panel">
        <header className="panel__head">
          <h2>표준 원가 (파우치 1개)</h2>
          <span className="muted erp__hint">배합비 × 자재 단가 + 가공비 · 모두 데모용 가상 값</span>
        </header>
        <div className="erp__costs">
          {costs.map((c) => (
            <div key={c.itemCode} className="erp__cost">
              <h3>{c.name}</h3>
              <div className="erp__cost-total">{won(c.total)}</div>
              <div className="muted">
                자재비 {won(c.material)} · 가공비 {won(c.conversion)}
              </div>
              <ul>
                {[...c.lines]
                  .sort((a, b) => b.amount - a.amount)
                  .slice(0, 5)
                  .map((l) => (
                    <li key={l.itemCode}>
                      {l.name} {l.uom === 'kg' && l.qty < 1 ? `${qty(Math.round(l.qty * 10000) / 10)} g` : `${qty(l.qty)} ${l.uom}`} ·{' '}
                      {won(l.amount)}
                    </li>
                  ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <p className="muted erp__foot">
        가상 ERP는 별도 서비스(:8090)와 별도 스키마(erp)로 돌고, 현장 관제(MES 역할, :8080)와는 API로만 주고받습니다.{' '}
        <button className="link-button" disabled={busy} onClick={() => void reset()}>
          ERP 데이터 초기화
        </button>
      </p>
    </main>
  )
}
