import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { LedgerRow, datasampleApi } from './api'

interface BatchBoundary {
  批次编号: string
  清单记录数: number
  去重记录数: number
  处理总次数: number
  层值分布: Record<string, number>
}

export default function DatasampleLedgerView() {
  const [rows, setRows] = useState<LedgerRow[]>([])
  const [boundary, setBoundary] = useState<BatchBoundary[]>([])
  const [errorMessage, setErrorMessage] = useState('')

  const reload = useCallback(async () => {
    setErrorMessage('')
    try {
      const payload = await datasampleApi.listLedger()
      setRows(payload.items)
      setBoundary((payload.批次边界 ?? []) as unknown as BatchBoundary[])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '保存侧清单读取失败')
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  return (
    <section className="page" data-module="datasample-ledger">
      <header className="page-head">
        <div>
          <h2>数据保存侧清单</h2>
          <p className="page-desc">
            样本数据集回写后按「批次 + 记录编号」去重；同一份样本数据集反复处理只算一次，
            仅累加处理次数。覆盖清单用于解释每个批次的样本边界。
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/datasample">返回抽样方案列表</Link>
        </div>
      </header>

      {errorMessage && <p className="error-text">{errorMessage}</p>}

      <h3 className="section-title">批次样本边界</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>批次编号</th>
            <th>清单记录数</th>
            <th>去重记录数</th>
            <th>处理总次数</th>
            <th>层值分布</th>
          </tr>
        </thead>
        <tbody>
          {boundary.map((item) => (
            <tr key={item.批次编号}>
              <td>{item.批次编号}</td>
              <td>{item.清单记录数}</td>
              <td>{item.去重记录数}</td>
              <td>{item.处理总次数}</td>
              <td>{Object.entries(item.层值分布).map(([key, value]) => `${key}:${value}`).join('、')}</td>
            </tr>
          ))}
          {boundary.length === 0 && (
            <tr><td className="empty-state" colSpan={5}>暂无回写记录，请先在结果版本里执行回写</td></tr>
          )}
        </tbody>
      </table>

      <h3 className="section-title">清单明细（批次去重结果）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>批次编号</th>
            <th>数据版本</th>
            <th>记录编号</th>
            <th>层值</th>
            <th>来源结果id</th>
            <th>最近结果id</th>
            <th>处理次数</th>
            <th>回写时间</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{row.批次编号}</td>
              <td>{row.数据版本}</td>
              <td>{row.记录编号}</td>
              <td>{row.层值}</td>
              <td>{row.来源结果id}</td>
              <td>{row.最近结果id}</td>
              <td>{row.处理次数}</td>
              <td>{row.回写时间}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr><td className="empty-state" colSpan={8}>清单为空</td></tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
