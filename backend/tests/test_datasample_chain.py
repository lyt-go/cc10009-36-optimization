"""数据抽样全链路验收：确定性、幂等、版本化、并发不分叉、保存侧去重回写。

运行：PYTHONPATH=. .venv/bin/python -I tests/test_datasample_chain.py
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.store import store  # noqa: E402
from app.services.datasample_pkg import DatasampleService, engine  # noqa: E402

svc = DatasampleService()
fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS" if cond else "FAIL"), "-", name, detail)
    if not cond:
        fails.append(name)


# ---------- 1. 首次执行：比例口径 vs 最小样本调整口径（小分层候选不足冲突）
payload, msg = svc.run_sampling(1)
check("首次执行成功", payload is not None, msg)
results = payload["结果"]
run1 = payload["运行"]
check("冲突产生两个结果版本", len(results) == 2, f"结果数={len(results)}")
modes = {r["口径"] for r in results}
check("两套口径齐全", modes == {"proportion", "min_adjusted"}, str(modes))

prop = next(r for r in results if r["口径"] == "proportion")
adj = next(r for r in results if r["口径"] == "min_adjusted")
check("比例口径样本量=目标5", prop["样本量"] == 5, str(prop["样本量"]))
check("最小调整口径样本量=8(每层至少2)", adj["样本量"] == 8, str(adj["样本量"]))
check("两口径样本量不同（冲突可追溯）", prop["样本量"] != adj["样本量"])

# 覆盖清单与样本数据集逐层核对
for r in results:
    cov_total = sum(c["实际样本数"] for c in r["覆盖清单"])
    check(f"覆盖清单总量==数据集({r['口径名称']})", cov_total == r["样本量"],
          f"{cov_total} vs {r['样本量']}")
    check(f"逐层核对一致({r['口径名称']})", r["覆盖核对一致"] is True)
    ds_ids = {item["记录编号"] for item in r["样本数据集"]}
    cov_ids = {rid for c in r["覆盖清单"] for rid in c["记录编号"]}
    check(f"覆盖清单记录与数据集完全对应({r['口径名称']})", ds_ids == cov_ids)
    check("每层保留随机依据", all(c["随机依据"].startswith("seed=") for c in r["覆盖清单"]))

# 层计划可追溯字段
layer_c = next(x for x in prop["层计划"] if x["层值"] == "C")
check("层行含候选数/调整量/冲突标记",
      layer_c["候选数"] == 7 and layer_c["调整量"] != 0 and layer_c["层冲突"] is True,
      str(layer_c))

# 优先级轨迹可回查
check("优先级轨迹按配额排序可回查",
      [t["优先级"] for t in adj["优先级轨迹"]] == list(range(1, len(adj["优先级轨迹"]) + 1)))

# ---------- 2. 幂等：同数据版本+方案版本重跑，不产生第二份结果
payload2, msg2 = svc.run_sampling(1)
check("重跑幂等返回同一运行", payload2["运行"]["id"] == run1["id"], msg2)
check("幂等标记为复用", payload2["幂等复用"] is True)
check("结果版本数量未增加", len(store.rows("sample_result")) == 2)
fp1 = prop["数据集指纹"]
check("数据集指纹稳定", payload2["结果"][0]["数据集指纹"] == fp1)

# 纯函数确定性：同一输入多次 compute_plan 完全一致
records = [dict(r) for r in store.rows("sample_batch_record") if r["批次编号"] in run1["批次范围"]]
p1 = engine.compute_plan(records=records, field="站点频道", ratio=0.10, min_sample=2)
p2 = engine.compute_plan(records=records, field="站点频道", ratio=0.10, min_sample=2)
check("compute_plan 纯函数确定", p1["层计划"] == p2["层计划"])

# 随机种子只绑定稳定输入：种子字符串不含时间，且两次派生一致
seed_a = engine.derive_seed("stratified-sampling", run1["数据指纹"], run1["方案指纹"], run1["批次范围"])
seed_b = engine.derive_seed("stratified-sampling", run1["数据指纹"], run1["方案指纹"], run1["批次范围"])
check("随机种子可复现且不随重跑改变", seed_a == seed_b)
check("随机依据声明无时间输入", "无时间" in run1["随机依据"])

# ---------- 3. 新增数据批次 -> 独立新版本结果，不与旧批次混用
new_records = [{"记录编号": f"ORD-300{i:03d}", "层值": "B", "内容摘要": "new batch"} for i in range(1, 9)]
batch, bmsg = svc.create_batch({
    "批次编号": "BATCH-20261117-01", "数据源": "抓取结果湖/order_pages",
    "数据版本": "dv-20261117-01", "分层字段": "站点频道", "records": new_records,
})
check("新批次入库", batch is not None, bmsg)
dup, dmsg = svc.create_batch({
    "批次编号": "BATCH-20261117-01", "数据源": "抓取结果湖/order_pages",
    "数据版本": "dv-x", "records": [],
})
check("重复批次编号被拒绝", dup is None, dmsg)

payload3, _ = svc.run_sampling(1)
run3 = payload3["运行"]
check("新批次产生新运行（不混用旧批次出第二份结果）", run3["id"] != run1["id"])
check("新运行覆盖全部三个批次", run3["批次范围"] == [
    "BATCH-20261115-01", "BATCH-20261116-01", "BATCH-20261117-01"])
check("数据指纹随批次变化", run3["数据指纹"] != run1["数据指纹"])
check("结果版本在方案内递增", {r["结果版本"] for r in payload3["结果"]} == {3, 4})
# 旧结果原样保留
check("历史结果未被覆盖", len(store.rows("sample_result")) == 4)

# 指定批次范围时，重跑仍幂等且不夹带其他批次
payload4, _ = svc.run_sampling(1, batch_codes=["BATCH-20261115-01"])
run4 = payload4["运行"]
check("指定批次范围独立成运行", run4["批次范围"] == ["BATCH-20261115-01"])
payload4b, _ = svc.run_sampling(1, batch_codes=["BATCH-20261115-01"])
check("指定范围重跑同样幂等", payload4b["运行"]["id"] == run4["id"])

# ---------- 4. 方案变更 -> 独立方案版本，历史结果保留
new_plan, rmsg = svc.revise_plan(1, {"抽样比例": 0.15, "最小样本量": 3, "零候选层": ["E"]})
check("方案变更生成新版本", new_plan is not None and new_plan["版本"] == 2, rmsg)
old_plan = store.find("datasample", 1)
check("老方案版本保留并停用", old_plan["版本"] == 1 and old_plan["版本状态"] == "已停用")
payload5, _ = svc.run_sampling(new_plan["id"])
check("新方案版本产生独立结果", all(r["方案版本"] == 2 for r in payload5["结果"]))
zero_rows = [c for c in payload5["结果"][0]["覆盖清单"] if c["零候选层"]]
check("零候选层 E 在覆盖清单留痕且不抽样",
      len(zero_rows) == 1 and zero_rows[0]["层值"] == "E" and zero_rows[0]["实际样本数"] == 0)
check("零候选层仍标记核对一致", zero_rows[0]["核对一致"] is True)
# v1 三次运行（全量两批/全量三批/单批）各 2 版 + v2 一次运行 2 版，历史全部保留
check("历史方案结果仍可查（共8个版本）", len(svc.list_results("DATA-0001")) == 8)

# ---------- 5. 并发：同方案+同批次范围同时触发，结果不分叉
barrier = threading.Barrier(4)
outs: list = []
def worker() -> None:
    barrier.wait()
    outs.append(svc.run_sampling(new_plan["id"]))
threads = [threading.Thread(target=worker) for _ in range(4)]
for t in threads:
    t.start()
for t in threads:
    t.join()
run_ids = {o[0]["运行"]["id"] for o in outs}
check("并发执行只产生一个运行（不分叉）", len(run_ids) == 1, str(run_ids))
check("并发调用全部幂等命中", all(o[0]["幂等复用"] for o in outs))

# ---------- 6. 保存侧回写：批次去重，重复处理只算一次
target = adj  # 最小调整口径结果（8 条）
wb1, wmsg = svc.writeback_result(target["id"])
check("首次回写全部新增", wb1 is not None and wb1["新增"] == 8 and wb1["重复跳过"] == 0, wmsg)
check("结果记录更新为已回写", target["保存侧状态"] == "已回写" and "回写时间" in target)
wb2, _ = svc.writeback_result(target["id"])
check("同一样本数据集反复处理只算一次", wb2["新增"] == 0 and wb2["重复跳过"] == 8)
ledger = svc.list_ledger()
check("清单无重复记录（批次+记录去重）", len(ledger) == 8 and
      len({(r["批次编号"], r["记录编号"]) for r in ledger}) == 8)
check("重复处理累加处理次数", all(int(r["处理次数"]) == 2 for r in ledger))

# 批次边界：覆盖清单解释样本边界
boundary = svc.ledger_boundary(target["批次范围"])
b1 = next(b for b in boundary if b["批次编号"] == "BATCH-20261115-01")
b2 = next(b for b in boundary if b["批次编号"] == "BATCH-20261116-01")
check("批次边界逐层可核对", b1["去重记录数"] + b2["去重记录数"] == 8, str(boundary))
check("边界含层值分布", sum(b1["层值分布"].values()) == b1["清单记录数"])

# 回写另一口径结果：跨结果的同一记录仍去重
wb3, _ = svc.writeback_result(prop["id"])
overlap = len({(i["批次编号"], i["记录编号"]) for i in prop["样本数据集"]}
              & {(i["批次编号"], i["记录编号"]) for i in adj["样本数据集"]})
check("跨结果回写按批次去重", wb3["新增"] == prop["样本量"] - overlap,
      f"新增={wb3['新增']} 重叠={overlap}")

# ---------- 7. 审计：调用链与优先级可回查
audit = svc.list_audit()
stages = {a["阶段"] for a in audit}
check("审计覆盖调用链各阶段",
      {"批次入库", "运行开始", "结果生成", "运行完成", "幂等命中", "保存侧回写", "方案变更"} <= stages,
      str(stages))

print()
print("失败项:", fails if fails else "无")
sys.exit(1 if fails else 0)
