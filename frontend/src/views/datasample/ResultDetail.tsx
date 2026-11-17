import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { SampleResult, datasampleApi } from './api'

export default function DatasampleResultView() {
  const { resultId } = useParams<{ resultId: string }>()
  const [result, setResult] = useState<SampleResult | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const [message, setMessage] = useState('')
  const [writing, setWriting] = useState(false)

  const reload = useCallback(async () => {
    if (!resultId) {
      return
    }
    setErrorMessage('')
    try {
      setResult(await datasampleApi.getResult(Number(resultId)))
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '覆盖详情读取失败')
    }
  }, [resultId])

  useEffect(() => {
    void reload()
  }, [reload])

  async function writeback() {
    if (!result) {
      return
    }
    setErrorMessage('')
    setMessage('')
    setWriting(true)
    try {
      const payload = await datasampleApi.writeback(result.id)
      const stat = payload.entry as { 新增: number; 重复跳过: number; 清单总量: number }
      setMessage(`已回写保存侧清单：新增 ${stat.新增} 条，重复跳过 ${stat.重复跳过} 条，清单总量 ${stat.清单总量}`)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '回写失败')
    } finally {
      setWriting(false)
    }
  }

  if (errorMessage && !result) {
    return (
      <section className="page">
        <p className="error-text">{errorMessage}</p>
        <Link className="btn" to="/datasample/runs">返回结果列表</Link>
      </section>
    )
  }
  if (!result) {
    return <section className="page"><p className="page-desc">覆盖详情加载中…</p></section>
  }

  return (
    <section className="page" data-module="datasample-result">
      <header className="page-head">
        <div>
          <h2>覆盖详情：{result.方案编号} v{result.方案版本} / 结果 r{result.结果版本}（{result.口径名称}）</h2>
          <p className="page-desc">
            批次范围 {result.批次范围.join('、')}；数据版本 {result.数据版本.join('、')}。
            覆盖清单与样本数据集逐层核对，调整量与返回列表后看到的结果保持一致。
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/datasample/runs">返回结果列表</Link>
          <Link className="btn" to="/datasample">返回抽样方案列表</Link>
          <button className="btn primary" type="button" disabled={writing} onClick={() => void writeback()}>
            {writing ? '回写中…' : '回写数据保存侧清单'}
          </button>
        </div>
      </header>

      {message && <p className="info-text">{message}</p>}
      {errorMessage && <p className="error-text">{errorMessage}</p>}

      <div className="stat-row">
        <article className="stat-card">
          <span className="stat-label">样本量 / 目标样本量</span>
          <strong className="stat-value">{result.样本量} / {result.目标样本量}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">覆盖核对</span>
          <strong className="stat-value">{result.覆盖核对一致 ? '逐层一致' : '不一致'}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">零候选层</span>
          <strong className="stat-value">{result.零候选层.length ? result.零候选层.join('、') : '无'}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">保存侧状态</span>
          <strong className="stat-value">{result.保存侧状态}</strong>
        </article>
      </div>

      <h3 className="section-title">随机依据（种子只绑定稳定输入，作业重跑不变）</h3>
      <p className="basis-cell">{result.随机依据}</p>
      <p className="page-desc">
        数据指纹 {result.数据指纹.slice(0, 18)}… ｜ 方案指纹 {result.方案指纹.slice(0, 18)}… ｜
        数据集指纹 {result.数据集指纹.slice(0, 18)}…
      </p>

      <h3 className="section-title">分层配额与最小样本调整（逐层核对）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>层值</th>
            <th>候选数</th>
            <th>比例配额</th>
            <th>最小样本配额</th>
            <th>调整量</th>
            <th>最小样本目标</th>
            <th>最小样本缺口</th>
            <th>零候选层</th>
            <th>层冲突</th>
          </tr>
        </thead>
        <tbody>
          {result.层计划.map((layer) => (
            <tr key={layer.层值}>
              <td>{layer.层值}</td>
              <td>{layer.候选数}</td>
              <td>{layer.比例配额}</td>
              <td>{layer.最小样本配额}</td>
              <td className={layer.调整量 > 0 ? 'adjust-up' : layer.调整量 < 0 ? 'adjust-down' : ''}>
                {layer.调整量 > 0 ? `+${layer.调整量}` : layer.调整量}
              </td>
              <td>{layer.最小样本目标}</td>
              <td>{layer.最小样本缺口}</td>
              <td>{layer.零候选层 ? '是' : '否'}</td>
              <td>{layer.层冲突 ? '是' : '否'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 className="section-title">样本覆盖清单（解释批次样本边界，含每层随机种子）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>层值</th>
            <th>候选数</th>
            <th>配额</th>
            <th>实际样本数</th>
            <th>零候选层</th>
            <th>层随机种子</th>
            <th>随机依据</th>
            <th>核对一致</th>
            <th>抽中记录编号</th>
          </tr>
        </thead>
        <tbody>
          {result.覆盖清单.map((coverage) => (
            <tr key={coverage.层值}>
              <td>{coverage.层值}</td>
              <td>{coverage.候选数}</td>
              <td>{coverage.配额}</td>
              <td>{coverage.实际样本数}</td>
              <td>{coverage.零候选层 ? '是' : '否'}</td>
              <td>{coverage.层随机种子}</td>
              <td className="basis-cell" title={coverage.随机依据}>{coverage.随机依据.split(';').slice(0, 2).join('；')}</td>
              <td>{coverage.核对一致 ? '一致' : '不一致'}</td>
              <td className="record-list">{coverage.记录编号.length ? coverage.记录编号.join('、') : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 className="section-title">优先级轨迹（配额决策可回查）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>优先级</th>
            <th>层值</th>
            <th>候选数</th>
            <th>采用配额</th>
            <th>调整量</th>
            <th>零候选层</th>
            <th>决策说明</th>
          </tr>
        </thead>
        <tbody>
          {result.优先级轨迹.map((trace) => (
            <tr key={String(trace.优先级)}>
              <td>{String(trace.优先级)}</td>
              <td>{String(trace.层值)}</td>
              <td>{String(trace.候选数)}</td>
              <td>{String(trace.采用配额)}</td>
              <td>{String(trace.调整量)}</td>
              <td>{trace.零候选层 ? '是' : '否'}</td>
              <td>{String(trace.决策说明)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 className="section-title">样本数据集（{result.样本数据集.length} 条，与覆盖清单记录一一对应）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>批次编号</th>
            <th>数据版本</th>
            <th>记录编号</th>
            <th>层值</th>
            <th>内容摘要</th>
            <th>入库时间</th>
          </tr>
        </thead>
        <tbody>
          {result.样本数据集.map((item) => (
            <tr key={String(item.记录编号)}>
              <td>{String(item.批次编号)}</td>
              <td>{String(item.数据版本)}</td>
              <td>{String(item.记录编号)}</td>
              <td>{String(item.层值)}</td>
              <td>{String(item.内容摘要)}</td>
              <td>{String(item.入库时间)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
