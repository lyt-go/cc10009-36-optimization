import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { Batch, Plan, SampleResult, SampleRun, datasampleApi } from './api'

const ENDPOINT = '/api/datasample'

interface LayerStat {
  层值: string
  候选数: number
  比例配额: number
  最小样本配额: number
  调整量: number
  零候选层: boolean
  层冲突: boolean
}

export default function DatasampleView() {
  const [plans, setPlans] = useState<Plan[]>([])
  const [batches, setBatches] = useState<Batch[]>([])
  const [runs, setRuns] = useState<SampleRun[]>([])
  const [results, setResults] = useState<SampleResult[]>([])
  const [message, setMessage] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [reviseId, setReviseId] = useState<number | null>(null)
  const [reviseForm, setReviseForm] = useState({ 抽样比例: '', 最小样本量: '', 零候选层: '' })

  const reload = useCallback(async () => {
    setErrorMessage('')
    try {
      const [planPage, batchPage, runPage, resultPage] = await Promise.all([
        datasampleApi.listPlans(),
        datasampleApi.listBatches(),
        datasampleApi.listRuns(),
        datasampleApi.listResults(),
      ])
      setPlans(planPage.items)
      setBatches(batchPage.items)
      setRuns(runPage.items)
      setResults(resultPage.items)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据抽样数据读取失败')
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  // 样本概览：按方案聚合分层规模、抽查比例与最小样本调整情况
  const overview = useMemo(() => {
    const layerAgg = new Map<string, LayerStat>()
    for (const result of results) {
      for (const layer of result.层计划) {
        const current = layerAgg.get(layer.层值) ?? {
          层值: layer.层值,
          候选数: 0,
          比例配额: 0,
          最小样本配额: 0,
          调整量: 0,
          零候选层: layer.零候选层,
          层冲突: false,
        }
        // 同一层在多批次结果里会重复出现，取最新结果（results 已按 id 倒序）的候选数
        if (current.候选数 === 0) {
          current.候选数 = layer.候选数
          current.比例配额 = layer.比例配额
          current.最小样本配额 = layer.最小样本配额
          current.调整量 = layer.调整量
          current.零候选层 = layer.零候选层
          current.层冲突 = layer.层冲突
        }
        layerAgg.set(layer.层值, current)
      }
    }
    const conflictResults = results.filter((item) => item.存在冲突).length
    const zeroLayers = new Set(results.flatMap((item) => item.零候选层))
    return {
      layers: [...layerAgg.values()],
      conflictResults,
      zeroLayerCount: zeroLayers.size,
      planCount: plans.length,
      enabledCount: plans.filter((item) => item.status === '已启用').length,
    }
  }, [plans, results])

  async function runSampling(plan: Plan) {
    setErrorMessage('')
    setMessage('')
    setBusyId(plan.id)
    try {
      const payload = await datasampleApi.runSampling(plan.id)
      setMessage(payload.message)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '抽样执行失败')
    } finally {
      setBusyId(null)
    }
  }

  async function planAction(plan: Plan, action: string) {
    setErrorMessage('')
    try {
      await datasampleApi.planAction(plan.id, action)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '方案动作未生效')
    }
  }

  function openRevise(plan: Plan) {
    setReviseId(plan.id)
    setReviseForm({
      抽样比例: String(plan.抽样比例 ?? ''),
      最小样本量: String(plan.最小样本量 ?? ''),
      零候选层: (plan.零候选层 ?? []).join(','),
    })
  }

  async function submitRevise(planId: number) {
    setErrorMessage('')
    try {
      const values: Record<string, unknown> = {
        抽样比例: Number(reviseForm.抽样比例),
        最小样本量: Number(reviseForm.最小样本量),
        零候选层: reviseForm.零候选层.split(',').map((item) => item.trim()).filter(Boolean),
      }
      await datasampleApi.revise(planId, values)
      setReviseId(null)
      setMessage('方案变更已生成独立新版本，历史结果保留')
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '方案变更失败')
    }
  }

  const latestResultByRun = useMemo(() => {
    const map = new Map<number, SampleResult>()
    for (const result of results) {
      if (!map.has(result.运行id)) {
        map.set(result.运行id, result)
      }
    }
    return map
  }, [results])

  return (
    <section className="page" data-module="datasample">
      <header className="page-head">
        <div>
          <h2>数据抽样管理</h2>
          <p className="page-desc">
            确定性分层抽样：相同数据版本与方案版本样本一致，覆盖清单与样本数据集逐层核对。
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/datasample/runs">抽样运行与结果版本</Link>
          <Link className="btn" to="/datasample/ledger">数据保存侧清单</Link>
          <Link className="btn" to="/datasample/audit">调用链审计</Link>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出抽样方案
          </button>
        </div>
      </header>

      <div className="stat-row">
        <article className="stat-card">
          <span className="stat-label">抽样方案版本数</span>
          <strong className="stat-value">{overview.planCount}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">已启用方案</span>
          <strong className="stat-value">{overview.enabledCount}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">分层数量（含零候选层 {overview.zeroLayerCount}）</span>
          <strong className="stat-value">{overview.layers.length}</strong>
        </article>
        <article className="stat-card">
          <span className="stat-label">最小样本调整冲突结果</span>
          <strong className="stat-value">{overview.conflictResults}</strong>
        </article>
      </div>

      {message && <p className="info-text">{message}</p>}
      {errorMessage && <p className="error-text">{errorMessage}</p>}

      <h3 className="section-title">样本概览：分层规模、抽查比例与最小样本调整</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>层值</th>
            <th>候选数（分层规模）</th>
            <th>比例配额</th>
            <th>最小样本配额</th>
            <th>最小样本调整量</th>
            <th>零候选层</th>
            <th>配额冲突</th>
          </tr>
        </thead>
        <tbody>
          {overview.layers.map((layer) => (
            <tr key={layer.层值}>
              <td>{layer.层值}</td>
              <td>{layer.候选数}</td>
              <td>{layer.比例配额}</td>
              <td>{layer.最小样本配额}</td>
              <td className={layer.调整量 > 0 ? 'adjust-up' : layer.调整量 < 0 ? 'adjust-down' : ''}>
                {layer.调整量 > 0 ? `+${layer.调整量}` : layer.调整量}
              </td>
              <td>{layer.零候选层 ? '是（仅覆盖清单留痕）' : '否'}</td>
              <td>{layer.层冲突 ? '是' : '否'}</td>
            </tr>
          ))}
          {overview.layers.length === 0 && (
            <tr><td className="empty-state" colSpan={7}>尚未执行抽样，执行后在此展示分层规模与调整情况</td></tr>
          )}
        </tbody>
      </table>

      <h3 className="section-title">抽样方案（含版本）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>方案编号</th>
            <th>版本</th>
            <th>数据源</th>
            <th>抽样方式</th>
            <th>抽查比例</th>
            <th>最小样本量</th>
            <th>分层字段</th>
            <th>零候选层</th>
            <th>状态</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {plans.map((plan) => (
            <tr key={plan.id}>
              <td>{plan.方案编号}</td>
              <td>v{plan.版本}{plan.父版本 ? `（源自 v${plan.父版本}）` : ''}</td>
              <td>{plan.数据源}</td>
              <td>{plan.抽样方式}</td>
              <td>{`${Math.round(Number(plan.抽样比例) * 100)}%`}</td>
              <td>{plan.最小样本量}</td>
              <td>{plan.分层字段}</td>
              <td>{(plan.零候选层 ?? []).length ? plan.零候选层.join('、') : '—'}</td>
              <td>{plan.status}</td>
              <td className="row-actions">
                <button className="link" type="button" disabled={busyId === plan.id} onClick={() => void runSampling(plan)}>
                  {busyId === plan.id ? '抽样中…' : '执行分层抽样'}
                </button>
                <button className="link" type="button" onClick={() => openRevise(plan)}>方案变更</button>
                {plan.status !== '已启用' && (
                  <button className="link" type="button" onClick={() => void planAction(plan, '启用方案')}>启用方案</button>
                )}
                {plan.status !== '已停用' && (
                  <button className="link" type="button" onClick={() => void planAction(plan, '停用方案')}>停用方案</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {reviseId !== null && (
        <form
          className="inline-form"
          onSubmit={(event) => { event.preventDefault(); void submitRevise(reviseId) }}
        >
          <h4>方案变更：为方案生成独立新版本（老版本与历史结果保留）</h4>
          <label className="filter-item">
            <span>抽查比例（0-1）</span>
            <input value={reviseForm.抽样比例} onChange={(e) => setReviseForm((p) => ({ ...p, 抽样比例: e.target.value }))} />
          </label>
          <label className="filter-item">
            <span>最小样本量</span>
            <input value={reviseForm.最小样本量} onChange={(e) => setReviseForm((p) => ({ ...p, 最小样本量: e.target.value }))} />
          </label>
          <label className="filter-item">
            <span>零候选层（逗号分隔）</span>
            <input value={reviseForm.零候选层} onChange={(e) => setReviseForm((p) => ({ ...p, 零候选层: e.target.value }))} />
          </label>
          <button className="btn primary" type="submit">生成新版本</button>
          <button className="btn ghost" type="button" onClick={() => setReviseId(null)}>取消</button>
        </form>
      )}

      <h3 className="section-title">数据批次（数据版本是抽样稳定输入）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>批次编号</th>
            <th>数据源</th>
            <th>数据版本</th>
            <th>记录总数</th>
            <th>创建时间</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          {batches.map((batch) => (
            <tr key={String(batch.id)}>
              <td>{String(batch.批次编号)}</td>
              <td>{String(batch.数据源)}</td>
              <td>{String(batch.数据版本)}</td>
              <td>{String(batch.记录总数)}</td>
              <td>{String(batch.创建时间)}</td>
              <td>{String(batch.说明)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 className="section-title">最近抽样运行（重复执行幂等，不混用新批次）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>运行编号</th>
            <th>方案</th>
            <th>批次范围</th>
            <th>数据指纹</th>
            <th>状态</th>
            <th>结果版本</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const linked = latestResultByRun.get(run.id)
            return (
              <tr key={run.id}>
                <td>{run.运行编号}</td>
                <td>{run.方案编号} v{run.方案版本}</td>
                <td>{run.批次范围.join('、')}</td>
                <td title={run.随机依据}>{run.数据指纹.slice(0, 12)}…</td>
                <td>{run.状态}</td>
                <td>
                  {linked ? (
                    <Link className="link" to={`/datasample/results/${linked.id}`}>
                      查看覆盖详情（{run.结果ids?.length ?? 0} 个版本）
                    </Link>
                  ) : '—'}
                </td>
              </tr>
            )
          })}
          {runs.length === 0 && (
            <tr><td className="empty-state" colSpan={6}>暂无抽样运行</td></tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
