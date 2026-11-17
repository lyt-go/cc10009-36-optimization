/** 数据抽样模块共享类型与请求封装。 */
import { request } from '@/api/client'

const ENDPOINT = '/api/datasample'

export interface Plan {
  id: number
  status: string
  方案编号: string
  数据源: string
  抽样方式: string
  抽样比例: number
  最小样本量: number
  分层字段: string
  抽样周期: string
  输出路径: string
  版本: number
  父版本: number | null
  版本状态: string
  零候选层: string[]
}

export interface CoverageRow {
  层值: string
  候选数: number
  配额: number
  实际样本数: number
  零候选层: boolean
  层随机种子: number
  随机依据: string
  记录编号: string[]
  核对一致: boolean
}

export interface LayerPlanRow {
  层值: string
  候选数: number
  比例配额: number
  最小样本配额: number
  最小样本目标: number
  调整量: number
  最小样本缺口: number
  零候选层: boolean
  层冲突: boolean
}

export interface SampleResult {
  id: number
  运行id: number
  方案编号: string
  方案版本: number
  结果版本: number
  口径: string
  口径名称: string
  批次范围: string[]
  数据版本: string[]
  数据指纹: string
  方案指纹: string
  数据集指纹: string
  层计划: LayerPlanRow[]
  覆盖清单: CoverageRow[]
  样本数据集: Array<Record<string, string | number>>
  样本量: number
  目标样本量: number
  存在冲突: boolean
  零候选层: string[]
  覆盖核对一致: boolean
  随机依据: string
  优先级轨迹: Array<Record<string, string | number | boolean>>
  保存侧状态: string
  回写时间?: string
  回写统计?: { 新增: number; 重复跳过: number; 清单总量: number }
  创建时间: string
}

export interface SampleRun {
  id: number
  运行编号: string
  方案id: number
  方案编号: string
  方案版本: number
  批次范围: string[]
  数据版本: string[]
  数据指纹: string
  方案指纹: string
  随机依据: string
  状态: string
  创建时间: string
  结果ids?: number[]
}

export interface Batch {
  id: number
  批次编号: string
  数据源: string
  数据版本: string
  记录总数: number
  创建时间: string
  说明: string
}

export interface LedgerRow {
  id: number
  批次编号: string
  数据版本: string
  记录编号: string
  层值: string
  来源结果id: number
  最近结果id: number
  处理次数: number
  回写时间: string
}

export interface AuditRow {
  id: number
  阶段: string
  说明: string
  运行id: number | null
  细节: Record<string, unknown>
  时间: string
}

interface PageEnvelope<T> {
  items: T[]
  total: number
}

async function getJson<T>(path: string): Promise<T> {
  const response = await request(`${ENDPOINT}${path}`)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}

async function postAction<T>(path: string, body: unknown = {}): Promise<T> {
  const response = await request(`${ENDPOINT}${path}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  const payload = (await response.json()) as T & { ok: boolean; message: string }
  if (!response.ok || !payload.ok) {
    throw new Error(payload.message || '操作未生效，请稍后重试')
  }
  return payload
}

export const datasampleApi = {
  listPlans: () => getJson<PageEnvelope<Plan>>('?size=200'),
  listBatches: () => getJson<PageEnvelope<Batch>>('/batches'),
  listRuns: () => getJson<PageEnvelope<SampleRun>>('/runs'),
  listResults: () => getJson<PageEnvelope<SampleResult>>('/results'),
  getResult: (id: number) => getJson<SampleResult>(`/results/${id}`),
  listLedger: () => getJson<PageEnvelope<LedgerRow> & { 批次边界: Array<Record<string, unknown>> }>('/ledger'),
  listAudit: () => getJson<PageEnvelope<AuditRow>>('/audit'),
  runSampling: (planId: number, batchCodes?: string[]) =>
    postAction<{ entry: { 运行: SampleRun; 结果: SampleResult[]; 幂等复用: boolean }; message: string }>(
      `/plans/${planId}/runs`,
      { values: { batch_codes: batchCodes ?? null } },
    ),
  writeback: (resultId: number) =>
    postAction<{ entry: Record<string, unknown>; message: string }>(`/results/${resultId}/writeback`),
  revise: (planId: number, values: Record<string, unknown>) =>
    postAction<{ entry: Plan; message: string }>(`/plans/${planId}/revise`, { values }),
  planAction: (planId: number, action: string) =>
    postAction<{ entry: Plan; message: string }>(`/plans/${planId}/actions`, { values: { action } }),
}
