import { useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'

import Overview from './views/Overview'
import WorkerView from './views/worker'
import DispatchView from './views/dispatch'
import CrawljobView from './views/crawljob'
import UrlfilterView from './views/urlfilter'
import DnsresolverView from './views/dnsresolver'
import ContentextractView from './views/contentextract'
import StoragestrategyView from './views/storagestrategy'
import RendertaskView from './views/rendertask'
import QualityreportView from './views/qualityreport'
import BandwidthView from './views/bandwidth'
import RetryqueueView from './views/retryqueue'
import PagemarkerView from './views/pagemarker'
import IncrementmarkView from './views/incrementmark'
import ConfigsyncView from './views/configsync'
import ScrapeapiView from './views/scrapeapi'
import DatasampleView from './views/datasample'
import DatasampleRunsView from './views/datasample/Runs'
import DatasampleResultView from './views/datasample/ResultDetail'
import DatasampleLedgerView from './views/datasample/Ledger'
import DatasampleAuditView from './views/datasample/Audit'
import AlertpolicyView from './views/alertpolicy'

const navItems = [{ label: "运营概览", path: "/" }, { label: "采集节点", path: "/worker" }, { label: "请求分配", path: "/dispatch" }, { label: "抓取作业", path: "/crawljob" }, { label: "URL过滤", path: "/urlfilter" }, { label: "DNS解析", path: "/dnsresolver" }, { label: "内容提取", path: "/contentextract" }, { label: "存储策略", path: "/storagestrategy" }, { label: "渲染任务", path: "/rendertask" }, { label: "采集质量", path: "/qualityreport" }, { label: "带宽控制", path: "/bandwidth" }, { label: "重试队列", path: "/retryqueue" }, { label: "翻页管理", path: "/pagemarker" }, { label: "增量标记", path: "/incrementmark" }, { label: "配置同步", path: "/configsync" }, { label: "采集API", path: "/scrapeapi" }, { label: "数据抽样", path: "/datasample" }, { label: "采集告警", path: "/alertpolicy" }]

export default function App() {
  const [operator] = useState('值班管理员')

  return (
    <div className="app-shell">
      <aside className="app-side">
        <h1 className="app-title">分布式网页抓取调度平台</h1>
        <nav className="nav-list">
          {navItems.map((item) => (
            <Link key={item.path} to={item.path} className="nav-item">
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="app-main">
        <header className="app-head">
          <span className="head-desc">面向分布式网页抓取任务调度、节点协同、请求分配、反爬策略编排、数据校验入库与抓取质量大盘的采集工程管理平台。</span>
          <span className="head-user">当前值班：{operator}</span>
        </header>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/worker" element={<WorkerView />} />
          <Route path="/dispatch" element={<DispatchView />} />
          <Route path="/crawljob" element={<CrawljobView />} />
          <Route path="/urlfilter" element={<UrlfilterView />} />
          <Route path="/dnsresolver" element={<DnsresolverView />} />
          <Route path="/contentextract" element={<ContentextractView />} />
          <Route path="/storagestrategy" element={<StoragestrategyView />} />
          <Route path="/rendertask" element={<RendertaskView />} />
          <Route path="/qualityreport" element={<QualityreportView />} />
          <Route path="/bandwidth" element={<BandwidthView />} />
          <Route path="/retryqueue" element={<RetryqueueView />} />
          <Route path="/pagemarker" element={<PagemarkerView />} />
          <Route path="/incrementmark" element={<IncrementmarkView />} />
          <Route path="/configsync" element={<ConfigsyncView />} />
          <Route path="/scrapeapi" element={<ScrapeapiView />} />
          <Route path="/datasample" element={<DatasampleView />} />
          <Route path="/datasample/runs" element={<DatasampleRunsView />} />
          <Route path="/datasample/results/:resultId" element={<DatasampleResultView />} />
          <Route path="/datasample/ledger" element={<DatasampleLedgerView />} />
          <Route path="/datasample/audit" element={<DatasampleAuditView />} />
          <Route path="/alertpolicy" element={<AlertpolicyView />} />
        </Routes>
      </main>
    </div>
  )
}
