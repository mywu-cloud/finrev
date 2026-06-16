import { useEffect, useCallback, useRef, useState, Component } from 'react'
import { useAppStore } from './store'
import StockSearch from './components/StockSearch'
import StockList from './components/StockList'
import RevenuePanel from './components/RevenuePanel'
import RankingPanel from './components/RankingPanel'
import styles from './App.module.css'

function fmtDateTime(dateStr) {
  if (!dateStr) return '--'
  const d = new Date(dateStr)
  if (isNaN(d)) return dateStr
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`
}

class AppErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{display:'flex',alignItems:'center',justifyContent:'center',height:'100vh',flexDirection:'column',fontFamily:'sans-serif',background:'#0f172a',color:'#e2e8f0',textAlign:'center',padding:'20px'}}>
          <h2 style={{color:'#f87171',marginBottom:'12px'}}>⚠ 應用程式發生錯誤</h2>
          <p style={{color:'#94a3b8',marginBottom:'16px'}}>{this.state.error?.message || '未知錯誤'}</p>
          <button onClick={() => window.location.reload()} style={{padding:'8px 16px',background:'#3b82f6',color:'#fff',border:'none',borderRadius:'6px',cursor:'pointer'}}>重新整理</button>
        </div>
      )
    }
    return this.props.children
  }
}

function AppContent() {
  const fetchStocks = useAppStore(s => s.fetchStocks)
  const searchQuery = useAppStore(s => s.searchQuery)
  const marketFilter = useAppStore(s => s.marketFilter)
  const industryFilter = useAppStore(s => s.industryFilter)
  const triggerSync = useAppStore(s => s.triggerSync)
  const selectedStock = useAppStore(s => s.selectedStock)
  const stocks = useAppStore(s => s.stocks)

  const [activeTab, setActiveTab] = useState('stocks')
  const [dataDate, setDataDate] = useState('')
  const debounceRef = useRef(null)

  const debouncedFetch = useCallback(() => {
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      fetchStocks()
    }, 300)
  }, [fetchStocks])

  useEffect(() => {
    debouncedFetch()
  }, [searchQuery, marketFilter, industryFilter])

  useEffect(() => {
    if (stocks && stocks.length > 0) {
      const latest = stocks.reduce((a, b) => {
        if (!a.updated_at) return b
        if (!b.updated_at) return a
        return new Date(a.updated_at) > new Date(b.updated_at) ? a : b
      }, stocks[0])
      if (latest && latest.updated_at) {
        setDataDate(fmtDateTime(latest.updated_at))
      }
    }
  }, [stocks])

  useEffect(() => {
    function scheduleRefresh() {
      const now = new Date()
      const next = new Date()
      next.setHours(20, 0, 0, 0)
      if (next <= now) next.setDate(next.getDate() + 1)
      const ms = next - now
      return setTimeout(async () => {
        await triggerSync(false)
        setTimeout(() => fetchStocks(), 3000)
        scheduleRefresh()
      }, ms)
    }
    const timer = scheduleRefresh()
    return () => clearTimeout(timer)
  }, [triggerSync, fetchStocks])

  return (
    <div className={styles.app}>
      <header className={styles.header}>
        <h1 className={styles.title}>台股月營收查詢</h1>
        <div className={styles.headerRight}>
          <span className={styles.dataDate}>
            資料日期：{dataDate || '--'}
          </span>
        </div>
      </header>

      <div className={styles.tabBar}>
        <button
          className={`${styles.tabBtn} ${activeTab === 'stocks' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('stocks')}
        >
          個股月營收
        </button>
        <button
          className={`${styles.tabBtn} ${activeTab === 'ranking' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('ranking')}
        >
          📊 營收月增率排行
        </button>
      </div>

      {activeTab === 'stocks' ? (
        <main className={styles.main}>
          <aside className={styles.sidebar}>
            <StockSearch />
            <StockList />
          </aside>
          <section className={styles.content}>
            {selectedStock ? (
              <RevenuePanel />
            ) : (
              <div className={styles.empty}>
                <div className={styles.emptyIcon}>📊</div>
                <p>請從左側選擇一支股票，查看月營收資料</p>
              </div>
            )}
          </section>
        </main>
      ) : (
        <main className={styles.mainFull}>
          <RankingPanel />
        </main>
      )}
    </div>
  )
}

export default function App() {
  return (
    <AppErrorBoundary>
      <AppContent />
    </AppErrorBoundary>
  )
}
