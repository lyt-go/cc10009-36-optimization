"""数据抽样接口。

调用链：抽样方案/数据批次 -> 分层抽样执行 -> 样本数据集与覆盖清单 ->
结果版本与优先级轨迹 -> 数据保存侧清单回写。状态与业务判断都在 service 层。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.datasample_pkg import DatasampleService

router = APIRouter(prefix="/api/datasample", tags=["数据抽样"])

service = DatasampleService()

LIST_FIELDS = ["方案编号", "数据源", "抽样方式", "抽样比例", "最小样本量", "分层字段", "抽样周期", "输出路径"]
STATUSES = ["草稿", "方案评审中", "已启用", "已停用"]


# ---------------------------------------------------------------- 抽样方案
@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按方案编号检索"),
    status: str | None = Query(default=None, description="草稿、方案评审中、已启用、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按方案编号与状态过滤抽样方案；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/plans/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条抽样方案明细（含版本信息）；不存在时给出可读错误。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"抽样方案 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条抽样方案，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="抽样方案已登记", entry=entry)


@router.post("/plans/{entry_id}/revise", response_model=ActionResult)
def revise_plan(entry_id: int, payload: EntryPayload) -> ActionResult:
    """方案变更：老版本保留停用，生成独立新版本，历史抽样结果不被覆盖。"""
    entry, message = service.revise_plan(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message or "方案新版本已生成", entry=entry)


@router.post("/plans/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条抽样方案执行提交方案评审、启用方案、停用方案。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出数据抽样方案清单：返回全量方案（含历史版本）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "datasample", "total": total, "items": items}


# ---------------------------------------------------------------- 数据批次
@router.get("/batches")
def list_batches(data_source: str | None = None) -> dict[str, Any]:
    """读取数据批次；批次携带数据版本，是抽样稳定输入的一部分。"""
    items = service.list_batches(data_source)
    return {"items": items, "total": len(items)}


@router.post("/batches", response_model=ActionResult)
def create_batch(payload: EntryPayload) -> ActionResult:
    """登记新数据批次及其记录；批次编号重复会被拒绝，避免数据版本指纹被污染。"""
    batch, message = service.create_batch(payload.values)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=f"批次 {batch['批次编号']} 已入库", entry=batch)


# ---------------------------------------------------------------- 抽样执行
@router.post("/plans/{plan_id}/runs", response_model=ActionResult)
def run_sampling(plan_id: int, payload: EntryPayload) -> ActionResult:
    """执行分层抽样。

    相同数据版本与方案版本幂等返回同一份结果；重复执行不会混用新批次生成
    第二份结果；并发执行按方案+批次范围加锁，结果不分叉。
    """
    batch_codes = payload.values.get("batch_codes") or None
    payload_data, message = service.run_sampling(plan_id, batch_codes=batch_codes)
    if payload_data is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=payload_data)


@router.get("/runs")
def list_runs() -> dict[str, Any]:
    """抽样运行列表：展示每次处理锁定的批次范围、数据指纹与随机依据。"""
    return {"items": service.list_runs(), "total": len(service.list_runs())}


@router.get("/results")
def list_results(plan_code: str | None = None) -> dict[str, Any]:
    """抽样结果版本列表；方案变更、批次新增、零候选层都会产生独立版本结果。"""
    items = service.list_results(plan_code)
    return {"items": items, "total": len(items)}


@router.get("/results/{result_id}")
def get_result(result_id: int) -> dict[str, Any]:
    """覆盖详情：样本数据集、逐层覆盖清单、优先级轨迹与随机依据一次取齐。"""
    result = service.get_result(result_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"抽样结果 {result_id} 不存在")
    return result


# ------------------------------------------------------------ 数据保存侧清单
@router.post("/results/{result_id}/writeback", response_model=ActionResult)
def writeback_result(result_id: int) -> ActionResult:
    """把样本数据集回写到数据保存侧清单并更新记录；按批次去重，重复处理只算一次。"""
    payload_data, message = service.writeback_result(result_id)
    if payload_data is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="样本数据集已回写数据保存侧清单", entry=payload_data)


@router.get("/ledger")
def list_ledger(batch_code: str | None = None) -> dict[str, Any]:
    """保存侧清单：覆盖清单用于解释该批次的样本边界。"""
    items = service.list_ledger(batch_code)
    return {
        "items": items,
        "total": len(items),
        "批次边界": service.ledger_boundary(
            sorted({row["批次编号"] for row in items})
        ),
    }


# ---------------------------------------------------------------- 审计轨迹
@router.get("/audit")
def list_audit(run_id: int | None = None) -> dict[str, Any]:
    """调用链审计：按执行阶段回查候选数、调整量与随机依据。"""
    items = service.list_audit(run_id)
    return {"items": items, "total": len(items)}
