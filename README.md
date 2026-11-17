# 分布式网页抓取调度平台

面向分布式网页抓取任务调度、节点协同、请求分配、反爬策略编排、数据校验入库与抓取质量大盘的采集工程管理平台。

这是一个前后端分离的管理平台：前端 React + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 React + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 采集节点 | `worker` | 工作节点 | 节点编号、主机地址、并发槽位数 |
| 请求分配 | `dispatch` | 分配策略 | 策略编号、目标域名、分配算法 |
| 抓取作业 | `crawljob` | 作业定义 | 作业编号、目标站点、起始URL |
| URL过滤 | `urlfilter` | 过滤规则 | 规则编号、包含模式、排除模式 |
| DNS解析 | `dnsresolver` | 解析配置 | 配置编号、域名模式、DNS服务器 |
| 内容提取 | `contentextract` | 提取器 | 提取器编号、内容类型、正文选择器 |
| 存储策略 | `storagestrategy` | 存储方案 | 方案编号、存储类型、连接参数 |
| 渲染任务 | `rendertask` | 渲染作业 | 作业编号、目标URL、浏览器版本 |
| 采集质量 | `qualityreport` | 质量报告 | 报告编号、作业编号、总URL数 |
| 带宽控制 | `bandwidth` | 带宽策略 | 策略编号、节点标识、下载带宽上限 |
| 重试队列 | `retryqueue` | 重试条目 | 条目编号、失败URL、失败原因码 |
| 翻页管理 | `pagemarker` | 翻页规则 | 规则编号、目标站点、翻页类型 |
| 增量标记 | `incrementmark` | 增量水位 | 水位编号、目标源、增量字段名 |
| 配置同步 | `configsync` | 同步任务 | 任务编号、源节点、目标节点 |
| 采集API | `scrapeapi` | API定义 | API编号、API名称、请求路径 |
| 数据抽样 | `datasample` | 抽样方案 | 方案编号、数据源、抽样方式 |
| 采集告警 | `alertpolicy` | 告警策略 | 策略编号、监控指标、触发条件 |

## 数据抽样：确定性分层抽样

数据抽样模块（后端 `app/services/datasample_pkg/`，前端
`frontend/src/views/datasample/`）围绕「结果可复现、覆盖可核对、版本可追溯」实现：

- **确定性**：随机种子只由稳定输入（数据指纹、方案指纹、批次范围）派生，不引用时间、
  内存地址或全局随机状态；相同数据版本与方案版本在任何进程、任何时间重跑都得到同一样本。
- **两套配额口径**：比例口径（Hamilton 最大余数法，候选数封顶）与最小样本调整口径
  （先保每层最小样本再按比例补齐）。小分层候选不足且总量仍满足总比例时，两套口径给出
  不同样本量，同一份样本数据集保留两个可追溯的结果版本。
- **幂等与并发**：按「方案 + 批次范围」加键锁，重复执行命中既有结果，不混用新批次生成
  第二份结果；并发触发只产生一个运行。
- **独立版本**：方案变更（老版本保留停用）、批次新增、零候选层都产生独立版本结果；
  零候选层不抽样，只在覆盖清单留痕。
- **覆盖核对**：样本覆盖清单逐层给出候选数、配额、实际样本数、层随机种子与随机依据，
  与样本数据集记录一一对应、逐层核对一致。
- **保存侧回写**：样本数据集回写到数据保存侧清单，按「批次 + 记录编号」去重；同一份
  样本数据集反复处理只算一次（仅累加处理次数），批次边界用覆盖清单解释。
- **调用链审计**：批次入库、运行开始、结果生成、幂等命中、保存侧回写等阶段全部留痕，
  优先级轨迹可回查。

### 数据抽样接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/datasample` | 抽样方案列表（含历史版本） |
| POST | `/api/datasample` | 登记抽样方案 |
| POST | `/api/datasample/plans/{id}/revise` | 方案变更，生成独立新版本 |
| POST | `/api/datasample/plans/{id}/actions` | 提交评审 / 启用 / 停用 |
| GET/POST | `/api/datasample/batches` | 数据批次（携带数据版本）查询/入库 |
| POST | `/api/datasample/plans/{id}/runs` | 执行分层抽样（幂等、并发安全） |
| GET | `/api/datasample/runs` | 抽样运行列表（数据指纹、随机依据） |
| GET | `/api/datasample/results` | 结果版本列表（比例/最小调整两口径） |
| GET | `/api/datasample/results/{id}` | 覆盖详情：层计划、覆盖清单、优先级轨迹、样本数据集 |
| POST | `/api/datasample/results/{id}/writeback` | 回写数据保存侧清单（批次去重） |
| GET | `/api/datasample/ledger` | 保存侧清单与批次样本边界 |
| GET | `/api/datasample/audit` | 调用链审计，可按运行回查 |

### 验收测试

```bash
cd backend
.venv/bin/python -I tests/test_datasample_chain.py          # 全链路（确定性/幂等/并发/去重）
.venv/bin/uvicorn app.main:app --port 8011 &               # 起服务后
BASE_URL=http://127.0.0.1:8011 .venv/bin/python -I tests/test_datasample_http.py
```

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据采集、爬虫与RPA
