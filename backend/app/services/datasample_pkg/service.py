"""数据抽样业务服务。

调用链（每个环节都落审计事件，优先级可回查）：

    数据批次/分层字段/抽样方案版本
        -> 构建稳定快照与数据指纹
        -> 确定性分层配额计算（比例口径 + 最小样本调整口径）
        -> 生成样本数据集与样本覆盖清单（逐层核对）
        -> 结果版本落库（同输入幂等，并发不分叉）
        -> 回写数据保存侧清单（按批次去重，重复处理只算一次）

并发控制：进程内按「方案+批次范围」加键锁，重复执行命中同一结果，
不会混用新数据批次生成第二份结果。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.services.datasample_pkg import engine
from app.services.datasample_pkg.engine import (
    MODE_LABELS,
    MODE_MIN_ADJUSTED,
    MODE_PROPORTION,
)
from app.store import store

PLAN_MODULE = "datasample"
BATCH_MODULE = "sample_batch"
RECORD_MODULE = "sample_batch_record"
RUN_MODULE = "sample_run"
RESULT_MODULE = "sample_result"
LEDGER_MODULE = "sample_ledger"
AUDIT_MODULE = "sample_audit"

PLAN_REQUIRED = ["方案编号", "数据源", "抽样方式"]
PLAN_STATUSES = ["草稿", "方案评审中", "已启用", "已停用"]
ACTION_RULES = {"提交方案评审": "方案评审中", "启用方案": "已启用", "停用方案": "已停用"}
NEGATIVE_ACTIONS = ["停用方案"]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _next_id(module: str) -> int:
    return max((int(row.get("id", 0)) for row in store.rows(module)), default=0) + 1


class DatasampleService:
    """抽样方案、批次、执行结果与保存侧清单的统一业务入口。"""

    _global_lock = threading.RLock()
    _key_locks: dict[str, threading.RLock] = {}

    # ------------------------------------------------------------------ 方案
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(PLAN_MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("方案编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(PLAN_MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in PLAN_REQUIRED if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(PLAN_MODULE)
        entry = {"id": _next_id(PLAN_MODULE)}
        entry.update(self._plan_fields(values))
        entry["status"] = PLAN_STATUSES[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["版本"] = 1
        entry["父版本"] = None
        entry["版本状态"] = PLAN_STATUSES[0]
        rows.append(entry)
        self._audit("方案登记", f"方案 {entry['方案编号']} v1 已登记", {"方案编号": entry["方案编号"]})
        return entry, []

    def revise_plan(self, plan_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """方案变更：老版本原样保留并停用，生成独立新版本；历史抽样结果不被覆盖。"""
        old = store.find(PLAN_MODULE, plan_id)
        if old is None:
            return None, f"抽样方案 {plan_id} 不存在或已归档"
        with self._global_lock:
            old["版本状态"] = "已停用"
            old["status"] = "已停用"
            new = {"id": _next_id(PLAN_MODULE)}
            new.update(self._plan_fields(values, fallback=old))
            new["方案编号"] = old["方案编号"]
            new["版本"] = int(old.get("版本", 1)) + 1
            new["父版本"] = old["版本"]
            new["status"] = PLAN_STATUSES[0]
            new["pending"] = True
            new["abnormal"] = False
            new["版本状态"] = PLAN_STATUSES[0]
            store.rows(PLAN_MODULE).append(new)
        self._audit(
            "方案变更",
            f"方案 {new['方案编号']} 由 v{old['版本']} 升级为 v{new['版本']}",
            {"方案编号": new["方案编号"], "新版本": new["版本"], "父版本": old["版本"]},
        )
        return new, ""

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(PLAN_MODULE, entry_id)
        if entry is None:
            return None, f"抽样方案 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据抽样可执行范围"
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["版本状态"] = target
        entry["pending"] = target != PLAN_STATUSES[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        self._audit("方案动作", f"方案 {entry['方案编号']} 执行 {action} -> {target}", {"action": action})
        return entry, f"抽样方案已{action}"

    @staticmethod
    def _plan_fields(values: dict[str, Any], fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        fields = ["方案编号", "数据源", "抽样方式", "抽样比例", "最小样本量",
                  "分层字段", "抽样周期", "输出路径", "零候选层"]
        out: dict[str, Any] = {}
        for field in fields:
            if field in values and values[field] is not None:
                out[field] = values[field]
            elif fallback is not None:
                out[field] = fallback.get(field)
        out["抽样比例"] = float(out.get("抽样比例") or 0)
        out["最小样本量"] = int(out.get("最小样本量") or 0)
        if not isinstance(out.get("零候选层"), list):
            out["零候选层"] = list(out.get("零候选层") or [])
        return out

    # ------------------------------------------------------------------ 批次
    def list_batches(self, data_source: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(BATCH_MODULE)
        if data_source:
            rows = [row for row in rows if row.get("数据源") == data_source]
        return rows

    def create_batch(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        code = str(values.get("批次编号") or "").strip()
        source = str(values.get("数据源") or "").strip()
        version = str(values.get("数据版本") or "").strip()
        if not code or not source or not version:
            return None, "批次编号、数据源、数据版本为必填项"
        if any(row.get("批次编号") == code for row in store.rows(BATCH_MODULE)):
            return None, f"批次 {code} 已存在，重复入库会破坏数据版本指纹"
        records = values.get("records") or []
        field = str(values.get("分层字段") or "层值")
        batch = {
            "id": _next_id(BATCH_MODULE),
            "批次编号": code,
            "数据源": source,
            "数据版本": version,
            "记录总数": len(records),
            "创建时间": _now(),
            "说明": values.get("说明") or "",
        }
        store.rows(BATCH_MODULE).append(batch)
        record_rows = store.rows(RECORD_MODULE)
        for index, item in enumerate(records, start=1):
            record_rows.append({
                "id": _next_id(RECORD_MODULE),
                "批次编号": code,
                "数据版本": version,
                "记录编号": str(item.get("记录编号") or f"{code}-R{index:04d}"),
                "分层字段": field,
                "层值": str(item.get("层值") or "未分层"),
                "内容摘要": str(item.get("内容摘要") or ""),
                "入库时间": _now(),
            })
        self._audit("批次入库", f"批次 {code}（{version}）入库 {len(records)} 条",
                    {"批次编号": code, "数据版本": version, "记录数": len(records)})
        return batch, ""

    # ------------------------------------------------------------------ 执行
    def run_sampling(
        self,
        plan_id: int,
        *,
        batch_codes: list[str] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        plan = store.find(PLAN_MODULE, plan_id)
        if plan is None:
            return None, f"抽样方案 {plan_id} 不存在或已归档"

        batches = self._resolve_batches(plan, batch_codes)
        if not batches:
            return None, "数据源下没有可抽样的数据批次"
        scope_codes = [row["批次编号"] for row in batches]
        lock_key = f"{plan['方案编号']}::v{plan['版本']}::{'/'.join(scope_codes)}"
        lock = self._key_locks.setdefault(lock_key, threading.RLock())

        with lock:
            return self._run_locked(plan, batches, lock_key)

    def _resolve_batches(
        self,
        plan: dict[str, Any],
        batch_codes: list[str] | None,
    ) -> list[dict[str, Any]]:
        rows = [row for row in store.rows(BATCH_MODULE) if row.get("数据源") == plan["数据源"]]
        if batch_codes:
            wanted = set(batch_codes)
            rows = [row for row in rows if row["批次编号"] in wanted]
        return sorted(rows, key=lambda row: str(row["批次编号"]))

    def _run_locked(
        self,
        plan: dict[str, Any],
        batches: list[dict[str, Any]],
        lock_key: str,
    ) -> tuple[dict[str, Any], str]:
        scope_codes = [row["批次编号"] for row in batches]
        records = [
            dict(row)
            for row in store.rows(RECORD_MODULE)
            if row["批次编号"] in set(scope_codes)
        ]
        records.sort(key=lambda row: (str(row["批次编号"]), str(row["记录编号"])))

        fingerprint_input = {
            "批次": [
                {"批次编号": row["批次编号"], "数据版本": row["数据版本"]}
                for row in batches
            ],
            "记录": [
                {"记录编号": row["记录编号"], "层值": row["层值"]}
                for row in records
            ],
        }
        data_fingerprint = engine.stable_hash(fingerprint_input)
        scheme_fingerprint = engine.stable_hash({
            "方案编号": plan["方案编号"],
            "版本": plan["版本"],
            "分层字段": plan["分层字段"],
            "抽样比例": plan["抽样比例"],
            "最小样本量": plan["最小样本量"],
            "零候选层": plan.get("零候选层") or [],
        })

        existing = [
            row for row in store.rows(RESULT_MODULE)
            if row.get("数据指纹") == data_fingerprint
            and row.get("方案指纹") == scheme_fingerprint
        ]
        if existing:
            # 同数据版本 + 同方案版本：直接返回既有结果，重跑不产生第二份结果
            run_id = existing[0]["运行id"]
            self._audit("幂等命中", f"运行 {run_id} 命中既有结果，未重新抽样",
                        {"数据指纹": data_fingerprint[:12], "结果数": len(existing)})
            return self._run_payload(run_id, reused=True), "相同数据版本与方案版本已存在一致样本，本次直接复用"

        run = {
            "id": _next_id(RUN_MODULE),
            "运行编号": f"RUN-{_now().replace('-', '').replace(':', '')}-{plan['方案编号']}",
            "方案id": plan["id"],
            "方案编号": plan["方案编号"],
            "方案版本": plan["版本"],
            "批次范围": scope_codes,
            "数据版本": [row["数据版本"] for row in batches],
            "数据指纹": data_fingerprint,
            "方案指纹": scheme_fingerprint,
            "随机依据": "",
            "状态": "计算中",
            "创建时间": _now(),
        }
        store.rows(RUN_MODULE).append(run)
        self._audit("运行开始", f"运行 {run['id']} 锁定批次范围 {scope_codes}",
                    {"运行id": run["id"], "批次范围": scope_codes})

        plan_calc = engine.compute_plan(
            records=records,
            field=str(plan["分层字段"]),
            ratio=float(plan["抽样比例"]),
            min_sample=int(plan["最小样本量"]),
            zero_strata=list(plan.get("零候选层") or []),
        )
        snapshot = plan_calc.pop("_snapshot")
        run_seed = engine.derive_seed(
            "stratified-sampling",
            data_fingerprint,
            scheme_fingerprint,
            scope_codes,
        )
        run["随机依据"] = (
            f"run_seed={run_seed};derived_from=sha256(数据指纹,方案指纹,批次范围);"
            "无时间/随机状态输入，作业重跑种子不变"
        )

        modes = [MODE_PROPORTION, MODE_MIN_ADJUSTED] if plan_calc["存在冲突"] else [MODE_PROPORTION]
        result_ids: list[int] = []
        per_plan_versions = self._next_result_versions(plan["方案编号"], len(modes))
        for mode, result_version in zip(modes, per_plan_versions):
            dataset, coverage = engine.pick_records(
                snapshot,
                plan_calc["层计划"],
                "比例配额" if mode == MODE_PROPORTION else "最小样本配额",
                run_seed=run_seed,
            )
            dataset_fingerprint = engine.stable_hash(
                [{"记录编号": item["记录编号"], "批次编号": item["批次编号"]} for item in dataset]
            )
            result = {
                "id": _next_id(RESULT_MODULE),
                "运行id": run["id"],
                "方案编号": plan["方案编号"],
                "方案版本": plan["版本"],
                "结果版本": result_version,
                "口径": mode,
                "口径名称": MODE_LABELS[mode],
                "批次范围": scope_codes,
                "数据版本": [row["数据版本"] for row in batches],
                "数据指纹": data_fingerprint,
                "方案指纹": scheme_fingerprint,
                "数据集指纹": dataset_fingerprint,
                "层计划": plan_calc["层计划"],
                "覆盖清单": coverage,
                "样本数据集": dataset,
                "样本量": len(dataset),
                "目标样本量": plan_calc["目标样本量"],
                "存在冲突": plan_calc["存在冲突"],
                "零候选层": [row["层值"] for row in plan_calc["层计划"] if row["零候选层"]],
                "覆盖核对一致": all(item["核对一致"] for item in coverage),
                "随机依据": run["随机依据"],
                "优先级轨迹": self._priority_trace(plan_calc["层计划"], mode),
                "保存侧状态": "待回写",
                "创建时间": _now(),
            }
            store.rows(RESULT_MODULE).append(result)
            result_ids.append(result["id"])
            self._audit(
                "结果生成",
                f"结果 {result['id']}（{MODE_LABELS[mode]}）样本量 {result['样本量']}",
                {"运行id": run["id"], "结果id": result["id"], "口径": mode,
                 "数据集指纹": dataset_fingerprint[:12],
                 "覆盖核对一致": result["覆盖核对一致"]},
            )

        run["状态"] = "已完成"
        run["结果ids"] = result_ids
        self._audit("运行完成", f"运行 {run['id']} 生成 {len(result_ids)} 个结果版本",
                    {"运行id": run["id"], "结果ids": result_ids})
        return self._run_payload(run["id"], reused=False), "抽样完成，样本数据集与覆盖清单已生成"

    def _next_result_versions(self, plan_code: str, count: int) -> list[int]:
        used = [
            int(row["结果版本"])
            for row in store.rows(RESULT_MODULE)
            if row.get("方案编号") == plan_code
        ]
        base = max(used, default=0)
        return [base + offset for offset in range(1, count + 1)]

    @staticmethod
    def _priority_trace(plan_rows: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
        """把分层配额的决策顺序固化下来，调用链上每一步都可回查。"""
        quota_field = "比例配额" if mode == MODE_PROPORTION else "最小样本配额"
        trace: list[dict[str, Any]] = []
        for priority, row in enumerate(
            sorted(plan_rows, key=lambda item: (-int(item[quota_field]), item["层值"])),
            start=1,
        ):
            trace.append({
                "优先级": priority,
                "层值": row["层值"],
                "候选数": row["候选数"],
                "采用配额": row[quota_field],
                "调整量": row["调整量"],
                "零候选层": row["零候选层"],
                "决策说明": (
                    "零候选层不抽样，仅在覆盖清单留痕"
                    if row["零候选层"]
                    else (
                        f"按{MODE_LABELS[mode]}取 {row[quota_field]}，"
                        f"相对比例口径调整 {row['调整量']:+d}"
                    )
                ),
            })
        return trace

    def _run_payload(self, run_id: int, *, reused: bool) -> dict[str, Any]:
        run = store.find(RUN_MODULE, run_id)
        results = [row for row in store.rows(RESULT_MODULE) if row["运行id"] == run_id]
        return {"运行": run, "结果": results, "幂等复用": reused}

    def list_runs(self) -> list[dict[str, Any]]:
        return sorted(store.rows(RUN_MODULE), key=lambda row: -int(row["id"]))

    def get_result(self, result_id: int) -> dict[str, Any] | None:
        return store.find(RESULT_MODULE, result_id)

    def list_results(self, plan_code: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(RESULT_MODULE)
        if plan_code:
            rows = [row for row in rows if row.get("方案编号") == plan_code]
        return sorted(rows, key=lambda row: -int(row["id"]))

    # -------------------------------------------------------------- 保存侧回写
    def writeback_result(self, result_id: int) -> tuple[dict[str, Any] | None, str]:
        result = store.find(RESULT_MODULE, result_id)
        if result is None:
            return None, f"抽样结果 {result_id} 不存在"
        lock = self._key_locks.setdefault(f"writeback::{result_id}", threading.RLock())
        with lock:
            ledger = store.rows(LEDGER_MODULE)
            existing_keys = {
                (row["批次编号"], row["记录编号"]) for row in ledger
            }
            inserted = 0
            duplicated = 0
            for item in result["样本数据集"]:
                key = (item["批次编号"], item["记录编号"])
                if key in existing_keys:
                    duplicated += 1
                    # 同一份样本数据集反复处理只算一次：仅累加处理次数，不新增清单记录
                    for row in ledger:
                        if (row["批次编号"], row["记录编号"]) == key:
                            row["处理次数"] = int(row.get("处理次数", 1)) + 1
                            row["最近结果id"] = result_id
                            break
                    continue
                ledger.append({
                    "id": _next_id(LEDGER_MODULE),
                    "批次编号": item["批次编号"],
                    "数据版本": item["数据版本"],
                    "记录编号": item["记录编号"],
                    "层值": item["层值"],
                    "来源结果id": result_id,
                    "最近结果id": result_id,
                    "处理次数": 1,
                    "回写时间": _now(),
                })
                existing_keys.add(key)
                inserted += 1

            result["保存侧状态"] = "已回写"
            result["回写时间"] = _now()
            result["回写统计"] = {"新增": inserted, "重复跳过": duplicated, "清单总量": len(ledger)}
            self._audit(
                "保存侧回写",
                f"结果 {result_id} 回写：新增 {inserted}，重复 {duplicated}",
                {"结果id": result_id, "新增": inserted, "重复跳过": duplicated},
            )
            return {
                "结果id": result_id,
                "新增": inserted,
                "重复跳过": duplicated,
                "清单总量": len(ledger),
                "批次边界": self.ledger_boundary(result["批次范围"]),
            }, ""

    def list_ledger(self, batch_code: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(LEDGER_MODULE)
        if batch_code:
            rows = [row for row in rows if row.get("批次编号") == batch_code]
        return rows

    def ledger_boundary(self, batch_codes: list[str]) -> list[dict[str, Any]]:
        """覆盖清单用于解释批次的样本边界：逐批次汇总保存侧清单。"""
        boundary: list[dict[str, Any]] = []
        for code in batch_codes:
            rows = [row for row in store.rows(LEDGER_MODULE) if row["批次编号"] == code]
            boundary.append({
                "批次编号": code,
                "清单记录数": len(rows),
                "去重记录数": len({row["记录编号"] for row in rows}),
                "处理总次数": sum(int(row.get("处理次数", 1)) for row in rows),
                "层值分布": self._count_by(rows, "层值"),
            })
        return boundary

    @staticmethod
    def _count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in rows:
            out[str(row.get(field))] = out.get(str(row.get(field)), 0) + 1
        return dict(sorted(out.items()))

    def list_audit(self, run_id: int | None = None) -> list[dict[str, Any]]:
        rows = store.rows(AUDIT_MODULE)
        if run_id is not None:
            rows = [row for row in rows if row.get("运行id") == run_id]
        return rows

    def _audit(self, stage: str, message: str, detail: dict[str, Any]) -> None:
        store.rows(AUDIT_MODULE).append({
            "id": _next_id(AUDIT_MODULE),
            "阶段": stage,
            "说明": message,
            "运行id": detail.get("运行id"),
            "细节": detail,
            "时间": _now(),
        })
