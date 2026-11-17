"""确定性分层抽样引擎。

设计目标（对应需求）：

1. 相同数据版本 + 方案版本必须得到完全一致的样本——随机种子只由稳定输入
   （数据指纹、方案编号、方案版本、批次范围）派生，不引用时间、内存地址或
   全局随机状态，作业重跑不会改变种子。
2. 每层输出两套配额口径：
   - ``proportion``：严格按总样本比例做最大余数法分配（受候选数封顶）；
   - ``min_adjusted``：先满足最小样本量，再把剩余配额按比例补齐。
   小分层候选不足、且总量仍可满足总比例时，两套口径给出不同样本量，即为
   「新旧记录冲突」，同一份样本数据集因此保留两个可追溯版本。
3. 每层记录候选数、比例配额、最小样本调整量、层随机种子与抽样依据，
   覆盖清单可与样本数据集逐层核对。
4. 零候选层单独标记，不参与随机抽样，只在覆盖清单里留痕。
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

# 两种配额口径：比例配额 / 最小样本调整后配额
MODE_PROPORTION = "proportion"
MODE_MIN_ADJUSTED = "min_adjusted"
MODE_LABELS = {
    MODE_PROPORTION: "比例配额",
    MODE_MIN_ADJUSTED: "最小样本调整",
}


def stable_hash(*parts: Any) -> str:
    """把任意稳定输入拼成 sha256 摘要；dict/list 会先按键排序序列化。"""
    joined = "|".join(_stable_text(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _stable_text(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(f"{k}={_stable_text(value[k])}" for k in sorted(value)) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_stable_text(item) for item in value) + "]"
    return str(value)


def derive_seed(*parts: Any) -> int:
    """从稳定输入派生整数种子；同一输入永远得到同一种子。"""
    return int(stable_hash(*parts)[:16], 16)


def largest_remainder(
    weights: dict[str, int],
    target: int,
    *,
    caps: dict[str, int] | None = None,
) -> dict[str, int]:
    """带封顶的最大余数法整数分配。

    - ``weights``：各层权重（这里用候选数）；
    - ``target``：希望分出去的总配额；
    - ``caps``：每层可承接的上限（候选数）。
    确定性：同权重、同目标、同封顶必然得到同一结果；余数并列时按层名排序，
    保证不同进程、不同执行时间的结果一致。
    """
    strata = sorted(weights)
    caps = caps or {name: target for name in strata}
    total_weight = sum(weights.values())
    alloc = {name: 0 for name in strata}
    if target <= 0 or total_weight <= 0:
        return alloc

    target = min(target, sum(caps[name] for name in strata))
    # Hamilton 最大余数法：先按比例取整（受封顶约束），再按小数余数从大到小补名额。
    # 余数并列时按层名字典序决出，集合/字典迭代顺序不影响结果，跨进程可复现。
    raw = {name: target * weights[name] / total_weight for name in strata}
    for name in strata:
        alloc[name] = min(int(raw[name]), caps[name])

    fractional = {name: raw[name] - int(raw[name]) for name in strata}
    leftover_order = sorted(strata, key=lambda name: (-fractional[name], name))
    for name in leftover_order:
        if sum(alloc.values()) >= target:
            break
        if alloc[name] >= caps[name]:
            continue
        alloc[name] += 1
    return alloc


def _sort_key(record: dict[str, Any]) -> tuple[str, str]:
    # 批次记录已把分层值规范化到「层值」列，「分层字段」只存字段名
    return (str(record.get("层值") or "未分层"), str(record.get("记录编号") or ""))


def build_snapshot(records: list[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    """按分层值把记录分组，组内按（层值、记录编号）排序——顺序稳定后随机抽样才可复现。"""
    snapshot: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        stratum = str(record.get("层值") or "未分层")
        snapshot.setdefault(stratum, []).append(dict(record))
    for stratum in snapshot:
        snapshot[stratum].sort(key=_sort_key)
    return dict(sorted(snapshot.items()))


def compute_plan(
    *,
    records: list[dict[str, Any]],
    field: str,
    ratio: float,
    min_sample: int,
    zero_strata: list[str] | None = None,
) -> dict[str, Any]:
    """纯函数：由稳定输入计算两套分层配额，不做任何 IO。

    返回每层的候选数、比例配额、最小样本调整配额、调整量与冲突标记，
    以及零候选层清单。调用方拿到的结果在任何机器、任何时间都一致。
    """
    snapshot = build_snapshot(records, field)
    strata = sorted(set(snapshot) | set(zero_strata or []))
    candidates = {name: len(snapshot.get(name, [])) for name in strata}
    total = len(records)
    target = round(total * ratio)

    # 口径一：纯比例，最大余数法，候选数封顶
    proportion = largest_remainder(
        weights={name: candidates[name] for name in strata if candidates[name] > 0},
        target=target,
        caps={name: candidates[name] for name in strata},
    )

    # 口径二：先保最小样本（候选不足时封顶到候选数），再按比例补齐剩余配额
    min_adjusted: dict[str, int] = {}
    min_shortfalls: dict[str, int] = {}
    for name in strata:
        wanted = min(min_sample, candidates[name])
        min_adjusted[name] = wanted
        if candidates[name] < min_sample:
            min_shortfalls[name] = min_sample - candidates[name]

    total_capacity = sum(candidates.values())
    min_total = sum(min_adjusted.values())
    remaining = max(target - min_total, 0)
    remaining = min(remaining, total_capacity - min_total)
    if remaining > 0:
        open_weights = {
            name: candidates[name] - min_adjusted[name]
            for name in strata
            if candidates[name] - min_adjusted[name] > 0
        }
        top_up = largest_remainder(
            weights=open_weights,
            target=remaining,
            caps=open_weights,
        )
        for name, extra in top_up.items():
            min_adjusted[name] += extra

    rows: list[dict[str, Any]] = []
    conflict = False
    for name in strata:
        prop_n = proportion.get(name, 0)
        adj_n = min_adjusted.get(name, 0)
        is_zero = candidates[name] == 0
        row = {
            "层值": name,
            "候选数": candidates[name],
            "比例配额": prop_n,
            "最小样本配额": adj_n,
            "最小样本目标": min_sample,
            "调整量": adj_n - prop_n,
            "最小样本缺口": min_shortfalls.get(name, 0),
            "零候选层": is_zero,
            "层冲突": (not is_zero) and prop_n != adj_n,
        }
        if row["层冲突"]:
            conflict = True
        rows.append(row)

    return {
        "分层字段": field,
        "总记录数": total,
        "目标样本量": target,
        "比例口径总量": sum(proportion.values()),
        "最小调整口径总量": sum(min_adjusted.values()),
        "存在冲突": conflict,
        "层计划": rows,
        "_snapshot": snapshot,
    }


def pick_records(
    snapshot: dict[str, list[dict[str, Any]]],
    plan_rows: list[dict[str, Any]],
    quota_field: str,
    *,
    run_seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按给定配额口径执行随机抽样。

    每层使用独立派生种子 ``sha256(run_seed, 层值)``，只消费排序后的稳定候选
    列表；返回（样本数据集, 覆盖清单层行）。覆盖清单里的层随机依据可直接复算。
    """
    dataset: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for row in plan_rows:
        name = row["层值"]
        quota = int(row[quota_field])
        members = snapshot.get(name, [])
        stratum_seed = derive_seed(run_seed, f"stratum:{name}")
        basis = f"seed={stratum_seed};candidates={len(members)};quota={quota};rule=random.Random.sample"
        if quota == 0 or not members:
            picked: list[dict[str, Any]] = []
        else:
            rng = random.Random(stratum_seed)
            indexes = sorted(rng.sample(range(len(members)), quota))
            picked = [members[index] for index in indexes]
        dataset.extend(picked)
        coverage.append({
            "层值": name,
            "候选数": len(members),
            "配额": quota,
            "实际样本数": len(picked),
            "零候选层": len(members) == 0,
            "层随机种子": stratum_seed,
            "随机依据": basis,
            "记录编号": [item.get("记录编号") for item in picked],
            "核对一致": len(picked) == quota,
        })
    return dataset, coverage
