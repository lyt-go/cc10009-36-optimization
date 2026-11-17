"""HTTP 层冒烟：通过真实 uvicorn 端口验证路由与调用链。

先启动服务：.venv/bin/uvicorn app.main:app --port 8011
再运行：BASE_URL=http://127.0.0.1:8011 .venv/bin/python -I tests/test_datasample_http.py
"""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
fails = []


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL"), "-", name, detail)
    if not cond:
        fails.append(name)


s, health = call("GET", "/api/health")
check("健康检查", s == 200 and health["ok"] is True)

s, plans = call("GET", "/api/datasample?size=200")
check("方案列表", s == 200 and plans["total"] >= 3, str(plans.get("total")))

s, batches = call("GET", "/api/datasample/batches")
check("批次列表含数据版本", s == 200 and batches["total"] == 2 and
      all("数据版本" in b for b in batches["items"]))

s, run1 = call("POST", "/api/datasample/plans/1/runs", {"values": {}})
check("执行抽样", s == 200 and run1["ok"] is True, run1.get("message", ""))
run_id = run1["entry"]["运行"]["id"]
result_ids = [r["id"] for r in run1["entry"]["结果"]]
check("返回两个结果版本", len(result_ids) == 2)

s, run2 = call("POST", "/api/datasample/plans/1/runs", {"values": {}})
check("HTTP 重跑幂等", run2["entry"]["运行"]["id"] == run_id and run2["entry"]["幂等复用"] is True)

s, detail = call("GET", f"/api/datasample/results/{result_ids[0]}")
check("覆盖详情含数据集/覆盖清单/优先级", s == 200 and
      all(k in detail for k in ("样本数据集", "覆盖清单", "优先级轨迹", "随机依据")))
check("详情层行可逐层核对", all(c["核对一致"] for c in detail["覆盖清单"]))

s, wb = call("POST", f"/api/datasample/results/{result_ids[0]}/writeback")
check("回写保存侧", s == 200 and wb["ok"] is True and wb["entry"]["新增"] > 0)

s, ledger = call("GET", "/api/datasample/ledger")
check("保存侧清单与批次边界", s == 200 and ledger["total"] > 0 and len(ledger["批次边界"]) == 2)

s, audit = call("GET", "/api/datasample/audit")
check("审计轨迹可回查", s == 200 and audit["total"] > 0)

s, revised = call("POST", "/api/datasample/plans/1/revise",
                  {"values": {"抽样比例": 0.2, "最小样本量": 4, "零候选层": ["E"]}})
check("方案变更新版本", s == 200 and revised["entry"]["版本"] == 2)

s, bad = call("POST", "/api/datasample/plans/999/runs", {"values": {}})
check("不存在方案返回可读错误", s == 200 and bad["ok"] is False)

s, dup = call("POST", "/api/datasample/batches",
              {"values": {"批次编号": "BATCH-20261115-01", "数据源": "x", "数据版本": "y"}})
check("重复批次被拒绝", dup["ok"] is False, dup.get("message", ""))

print()
print("失败项:", fails if fails else "无")
sys.exit(1 if fails else 0)
