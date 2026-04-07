import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useAppStore } from '../../stores/useAppStore';
import { formatCurrency, formatPercent } from '../../utils/helpers';
import type { BarData } from '../../stores/types';
import api from '../../services/api';

const TF_MAP: Record<string, string> = {
  '1Min': '1Min', '5Min': '5Min', '15Min': '15Min',
  '1H': '1H', '4H': '4H', '1D': '1Day', '1W': '1Week',
};

const ChartView: React.FC = () => {
  const { selectedSymbol, setSelectedSymbol, watchlist } = useAppStore();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [timeframe, setTimeframe] = useState('1D');
  const [searchInput, setSearchInput] = useState(selectedSymbol);
  const [candleData, setCandleData] = useState<BarData[]>([]);
  const [hoveredCandle, setHoveredCandle] = useState<BarData | null>(null);
  const [indicators, setIndicators] = useState({ ma20: true, ma50: true, volume: true });
  const [loading, setLoading] = useState(false);

  const currentItem = watchlist.find(w => w.symbol === selectedSymbol);

  // ── Fetch real bars from Alpaca ──────────────────────────
  useEffect(() => {
    let cancelled = false;
    const fetchBars = async () => {
      setLoading(true);
      try {
        const tf = TF_MAP[timeframe] || '1Day';
        const data = await api.getBars(selectedSymbol, tf, 150) as { bars?: BarData[] };
        if (!cancelled && data?.bars && data.bars.length > 0) {
          setCandleData(data.bars);
        }
      } catch (e) {
        console.error('Failed to fetch bars:', e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchBars();
    // Refresh every 30s
    const interval = setInterval(fetchBars, 30000);
    return () => { cancelled = true; clearInterval(interval); };
  }, [selectedSymbol, timeframe]);

  // Draw the chart on canvas
  const drawChart = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || candleData.length === 0) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const width = rect.width;
    const height = rect.height;
    const chartHeight = indicators.volume ? height * 0.75 : height - 20;
    const volumeHeight = height * 0.2;
    const volumeTop = chartHeight + 10;

    // Clear
    ctx.fillStyle = '#060a13';
    ctx.fillRect(0, 0, width, height);

    // Calculate price range
    const visibleData = candleData.slice(-80);
    const prices = visibleData.flatMap(d => [d.high, d.low]);
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const priceRange = maxPrice - minPrice || 1;
    const padding = priceRange * 0.08;
    const adjustedMin = minPrice - padding;
    const adjustedMax = maxPrice + padding;
    const adjustedRange = adjustedMax - adjustedMin;

    const candleWidth = (width - 60) / visibleData.length;
    const bodyWidth = Math.max(candleWidth * 0.6, 2);

    // Grid lines
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.06)';
    ctx.lineWidth = 1;
    const gridLines = 6;
    for (let i = 0; i <= gridLines; i++) {
      const y = (i / gridLines) * chartHeight;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width - 50, y);
      ctx.stroke();

      // Price labels
      const price = adjustedMax - (i / gridLines) * adjustedRange;
      ctx.fillStyle = '#64748b';
      ctx.font = '11px Inter, sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(price.toFixed(2), width - 4, y + 3);
    }

    // Calculate MAs
    const ma20: number[] = [];
    const ma50: number[] = [];
    for (let i = 0; i < visibleData.length; i++) {
      const startIdx = candleData.length - visibleData.length + i;
      if (startIdx >= 20) {
        const slice = candleData.slice(startIdx - 20, startIdx).map(d => d.close);
        ma20.push(slice.reduce((a, b) => a + b, 0) / 20);
      } else {
        ma20.push(NaN);
      }
      if (startIdx >= 50) {
        const slice = candleData.slice(startIdx - 50, startIdx).map(d => d.close);
        ma50.push(slice.reduce((a, b) => a + b, 0) / 50);
      } else {
        ma50.push(NaN);
      }
    }

    // Draw MA lines
    const drawMA = (values: number[], color: string) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      let started = false;
      values.forEach((val, i) => {
        if (isNaN(val)) return;
        const x = i * candleWidth + candleWidth / 2;
        const y = ((adjustedMax - val) / adjustedRange) * chartHeight;
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.stroke();
    };

    if (indicators.ma20) drawMA(ma20, 'rgba(0, 212, 170, 0.6)');
    if (indicators.ma50) drawMA(ma50, 'rgba(99, 102, 241, 0.6)');

    // Draw candles
    visibleData.forEach((candle, i) => {
      const x = i * candleWidth + candleWidth / 2;
      const isUp = candle.close >= candle.open;

      const openY = ((adjustedMax - candle.open) / adjustedRange) * chartHeight;
      const closeY = ((adjustedMax - candle.close) / adjustedRange) * chartHeight;
      const highY = ((adjustedMax - candle.high) / adjustedRange) * chartHeight;
      const lowY = ((adjustedMax - candle.low) / adjustedRange) * chartHeight;

      // Wick
      ctx.strokeStyle = isUp ? '#10b981' : '#ef4444';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, highY);
      ctx.lineTo(x, lowY);
      ctx.stroke();

      // Body
      ctx.fillStyle = isUp ? '#10b981' : '#ef4444';
      const top = Math.min(openY, closeY);
      const bodyHeight = Math.max(Math.abs(closeY - openY), 1);
      ctx.fillRect(x - bodyWidth / 2, top, bodyWidth, bodyHeight);
    });

    // Volume bars
    if (indicators.volume) {
      const maxVol = Math.max(...visibleData.map(d => d.volume || 0));
      visibleData.forEach((candle, i) => {
        const x = i * candleWidth;
        const vol = candle.volume || 0;
        const volHeight = (vol / maxVol) * volumeHeight;
        const isUp = candle.close >= candle.open;

        ctx.fillStyle = isUp ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)';
        ctx.fillRect(x + 1, volumeTop + volumeHeight - volHeight, candleWidth - 2, volHeight);
      });
    }

    // Current price line
    const lastCandle = visibleData[visibleData.length - 1];
    if (lastCandle) {
      const lastY = ((adjustedMax - lastCandle.close) / adjustedRange) * chartHeight;
      const isUp = lastCandle.close >= lastCandle.open;

      ctx.strokeStyle = isUp ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)';
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, lastY);
      ctx.lineTo(width - 50, lastY);
      ctx.stroke();
      ctx.setLineDash([]);

      // Price label
      ctx.fillStyle = isUp ? '#10b981' : '#ef4444';
      ctx.fillRect(width - 52, lastY - 10, 52, 20);
      ctx.fillStyle = 'white';
      ctx.font = 'bold 11px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(lastCandle.close.toFixed(2), width - 26, lastY + 4);
    }
  }, [candleData, indicators]);

  useEffect(() => {
    drawChart();

    // ResizeObserver watches the canvas container so chart redraws
    // when the flex layout settles (fixes the blank chart on first load)
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(() => drawChart());
    observer.observe(canvas.parentElement || canvas);
    return () => observer.disconnect();
  }, [drawChart]);

  // Extra redraw trigger: when loading finishes and data arrives, force redraw after layout paint
  useEffect(() => {
    if (!loading && candleData.length > 0) {
      requestAnimationFrame(() => drawChart());
    }
  }, [loading, candleData.length]);

  const lastCandle = candleData[candleData.length - 1];
  const displayCandle = hoveredCandle || lastCandle;

  const timeframes = ['1Min', '5Min', '15Min', '1H', '4H', '1D', '1W'];

  return (
    <div className="page-enter" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 64px - 48px)' }}>
      {/* Chart Toolbar */}
      <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <div className="card-header" style={{ gap: '16px', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div className="chart-symbol-search">
              <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>🔍</span>
              <input
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value.toUpperCase())}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    setSelectedSymbol(searchInput);
                  }
                }}
                placeholder="AAPL"
              />
            </div>

            {currentItem && (
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
                <span style={{
                  fontSize: '20px',
                  fontWeight: 800,
                  fontFamily: 'var(--font-mono)',
                }}>
                  {formatCurrency(displayCandle?.close || currentItem.price)}
                </span>
                <span style={{
                  fontSize: '13px',
                  fontWeight: 600,
                  color: currentItem.change >= 0 ? 'var(--profit)' : 'var(--loss)',
                }}>
                  {currentItem.change >= 0 ? '▲' : '▼'} {formatCurrency(Math.abs(currentItem.change))} ({formatPercent(currentItem.changePercent)})
                </span>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div className="chart-timeframe">
              {timeframes.map((tf) => (
                <button
                  key={tf}
                  className={timeframe === tf ? 'active' : ''}
                  onClick={() => setTimeframe(tf)}
                >
                  {tf}
                </button>
              ))}
            </div>

            <div style={{ display: 'flex', gap: '4px' }}>
              <button
                className={`btn btn-sm ${indicators.ma20 ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setIndicators(prev => ({ ...prev, ma20: !prev.ma20 }))}
                style={{ fontSize: '10px' }}
              >
                MA20
              </button>
              <button
                className={`btn btn-sm ${indicators.ma50 ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setIndicators(prev => ({ ...prev, ma50: !prev.ma50 }))}
                style={{ fontSize: '10px' }}
              >
                MA50
              </button>
              <button
                className={`btn btn-sm ${indicators.volume ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => setIndicators(prev => ({ ...prev, volume: !prev.volume }))}
                style={{ fontSize: '10px' }}
              >
                VOL
              </button>
            </div>
          </div>
        </div>

        {/* OHLCV Info Bar */}
        {displayCandle && (
          <div style={{
            display: 'flex',
            gap: '24px',
            padding: '8px 20px',
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-tertiary)',
            borderBottom: '1px solid var(--border-secondary)',
          }}>
            <span>O <span style={{ color: 'var(--text-primary)' }}>{displayCandle.open.toFixed(2)}</span></span>
            <span>H <span style={{ color: 'var(--profit)' }}>{displayCandle.high.toFixed(2)}</span></span>
            <span>L <span style={{ color: 'var(--loss)' }}>{displayCandle.low.toFixed(2)}</span></span>
            <span>C <span style={{ color: displayCandle.close >= displayCandle.open ? 'var(--profit)' : 'var(--loss)' }}>{displayCandle.close.toFixed(2)}</span></span>
            {displayCandle.volume && (
              <span>V <span style={{ color: 'var(--text-secondary)' }}>{(displayCandle.volume / 1000).toFixed(1)}K</span></span>
            )}
          </div>
        )}

        {/* Canvas Chart */}
        <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
          {loading && (
            <div style={{
              position: 'absolute', inset: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'rgba(6,10,19,0.8)', zIndex: 10, gap: '12px',
              fontSize: '13px', color: 'var(--text-tertiary)',
            }}>
              <span style={{ animation: 'spin 1s linear infinite', display: 'inline-block' }}>⟳</span>
              Alpaca에서 차트 데이터 로딩 중...
            </div>
          )}
          {!loading && candleData.length === 0 && (
            <div style={{
              position: 'absolute', inset: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexDirection: 'column', gap: '8px',
              fontSize: '13px', color: 'var(--text-tertiary)',
            }}>
              <span style={{ fontSize: '32px' }}>📭</span>
              <span>이 종목의 차트 데이터가 없습니다</span>
            </div>
          )}
          <canvas
            ref={canvasRef}
            style={{ width: '100%', height: '100%', cursor: 'crosshair' }}
            onMouseMove={(e) => {
              const rect = canvasRef.current?.getBoundingClientRect();
              if (!rect) return;
              const visibleData = candleData.slice(-80);
              const candleWidth = (rect.width - 60) / visibleData.length;
              const idx = Math.floor(e.clientX / candleWidth);
              if (idx >= 0 && idx < visibleData.length) {
                setHoveredCandle(visibleData[idx]);
              }
            }}
            onMouseLeave={() => setHoveredCandle(null)}
          />
        </div>
      </div>

      {/* Bottom Quick Symbols */}
      <div style={{
        display: 'flex',
        gap: '8px',
        marginTop: '12px',
        overflowX: 'auto',
        paddingBottom: '4px',
      }}>
        {watchlist.map((item) => (
          <button
            key={item.symbol}
            className={`btn btn-sm ${selectedSymbol === item.symbol ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => {
              setSelectedSymbol(item.symbol);
              setSearchInput(item.symbol);
            }}
            style={{ flexShrink: 0 }}
          >
            {item.symbol}
            <span style={{
              color: item.change >= 0 ? 'var(--profit)' : 'var(--loss)',
              marginLeft: '4px',
            }}>
              {formatPercent(item.changePercent)}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
};

export default ChartView;
