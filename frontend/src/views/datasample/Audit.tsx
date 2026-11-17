import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { AuditRow, datasampleApi } from './api'

const STAGE_ORDER = ['批次入库', '方案登记', '方案动作', '方案变更', '运行开始', '结果生成', '运行完成', '幂等命中', '保存侧回写']

export default function DatasampleAuditView() {
  const [rows, setRows] = useState<AuditRow[]>([])
  const [stage, setStage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')

  const reload = useCallback(async () => {
    setErrorMessage('')
    try {
      const payload = await datasampleApi.listAudit()
      setRows(payload.items)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '审计轨迹读取失败')
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const filtered = stage ? rows.filter((row) => row.阶段 === stage) : rows
  const ordered = [...filtered].sort(
    (a, b) => STAGE_ORDER.indexOf(a.阶段) - STAGE_ORDER.indexOf(b.阶段) || b.id - a.id,
  )

  return (
    <section className="page" data-module="datasample-audit">
      <header className="page-head">
        <div>
          <h2>调用链审计</h2>
          <p className="page-desc">
            按调用链阶段回查候选数、调整量、随机依据与回写统计；每个抽样动作都在此留痕。
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/datasample">返回抽样方案列表</Link>
        </div>
      </header>

      {errorMessage && <p className="error-text">{errorMessage}</p>}

      <form className="filter-bar" onSubmit={(event) => event.preventDefault()}>
        <label className="filter-item">
          <span>调用链阶段</span>
          <select value={stage} onChange={(event) => setStage(event.target.value)}>
            <option value="">全部阶段</option>
            {STAGE_ORDER.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>阶段（调用链）</th>
            <th>说明</th>
            <th>运行id</th>
            <th>细节（候选数/调整量/随机依据可回查）</th>
          </tr>
        </thead>
        <tbody>
          {ordered.map((row) => (
            <tr key={row.id}>
              <td>{row.时间}</td>
              <td>{row.阶段}</td>
              <td>{row.说明}</td>
              <td>{row.运行id ?? '—'}</td>
              <td className="basis-cell">{JSON.stringify(row.细节)}</td>
            </tr>
          ))}
          {ordered.length === 0 && (
            <tr><td className="empty-state" colSpan={5}>暂无审计记录</td></tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
