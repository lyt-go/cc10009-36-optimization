import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { SampleResult, SampleRun, datasampleApi } from './api'

export default function DatasampleRunsView() {
  const [runs, setRuns] = useState<SampleRun[]>([])
  const [results, setResults] = useState<SampleResult[]>([])
  const [errorMessage, setErrorMessage] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)

  const reload = useCallback(async () => {
    setErrorMessage('')
    try {
      const [runPage, resultPage] = await Promise.all([
        datasampleApi.listRuns(),
        datasampleApi.listResults(),
      ])
      setRuns(runPage.items)
      setResults(resultPage.items)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '抽样运行读取失败')
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  async function writeback(result: SampleResult) {
    setErrorMessage('')
    setBusyId(result.id)
    try {
      await datasampleApi.writeback(result.id)
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '回写数据保存侧失败')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="page" data-module="datasample-runs">
      <header className="page-head">
        <div>
          <h2>抽样运行与结果版本</h2>
          <p className="page-desc">
            相同数据版本与方案版本只保留一致样本；方案变更、批次新增、零候选层均产生独立版本结果。
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/datasample">返回抽样方案列表</Link>
        </div>
      </header>

      {errorMessage && <p className="error-text">{errorMessage}</p>}

      <h3 className="section-title">运行记录（随机种子只绑定稳定输入，重跑不变）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>运行编号</th>
            <th>方案版本</th>
            <th>批次范围</th>
            <th>数据版本</th>
            <th>数据指纹</th>
            <th>随机依据</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>{run.运行编号}</td>
              <td>{run.方案编号} v{run.方案版本}</td>
              <td>{run.批次范围.join('、')}</td>
              <td>{run.数据版本.join('、')}</td>
              <td title={run.数据指纹}>{run.数据指纹.slice(0, 12)}…</td>
              <td className="basis-cell" title={run.随机依据}>{run.随机依据.split(';')[0]}</td>
              <td>{run.状态}</td>
            </tr>
          ))}
          {runs.length === 0 && (
            <tr><td className="empty-state" colSpan={7}>暂无运行，请先在方案列表执行分层抽样</td></tr>
          )}
        </tbody>
      </table>

      <h3 className="section-title">样本结果版本（比例口径 / 最小样本调整口径）</h3>
      <table className="data-table">
        <thead>
          <tr>
            <th>结果id</th>
            <th>方案版本</th>
            <th>结果版本</th>
            <th>口径</th>
            <th>批次范围</th>
            <th>样本量/目标量</th>
            <th>冲突</th>
            <th>覆盖核对</th>
            <th>保存侧状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {results.map((result) => (
            <tr key={result.id}>
              <td>{result.id}</td>
              <td>{result.方案编号} v{result.方案版本}</td>
              <td>r{result.结果版本}</td>
              <td>{result.口径名称}</td>
              <td>{result.批次范围.join('、')}</td>
              <td>{result.样本量} / {result.目标样本量}</td>
              <td>{result.存在冲突 ? '两套口径并存' : '无冲突'}</td>
              <td>{result.覆盖核对一致 ? '逐层一致' : '不一致'}</td>
              <td>
                {result.保存侧状态}
                {result.回写统计 ? `（新增${result.回写统计.新增}/重复${result.回写统计.重复跳过}）` : ''}
              </td>
              <td className="row-actions">
                <Link className="link" to={`/datasample/results/${result.id}`}>覆盖详情</Link>
                <button
                  className="link"
                  type="button"
                  disabled={busyId === result.id}
                  onClick={() => void writeback(result)}
                >
                  {busyId === result.id ? '回写中…' : '回写保存侧'}
                </button>
              </td>
            </tr>
          ))}
          {results.length === 0 && (
            <tr><td className="empty-state" colSpan={10}>暂无结果版本</td></tr>
          )}
        </tbody>
      </table>
    </section>
  )
}
