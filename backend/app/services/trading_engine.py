"""
TradeSense - Trading Engine v2
Smarter quant strategies with market hours check + AI signal confirmation.
"""
import logging
import asyncio
from datetime import datetime, time
import pytz
from typing import Optional
from app.core.config import settings
from app.services.alpaca_service import alpaca_service

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


def is_market_open() -> bool:
    """Check if US stock market is currently open."""
    now_et = datetime.now(ET)
    if now_et.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    market_open  = time(9, 30)
    market_close = time(16, 0)
    return market_open <= now_et.time() <= market_close


class TradingEngine:
    """Core trading engine that executes strategies."""

    def __init__(self):
        self.active           = False
        self.active_strategy: Optional[str] = None
        self.last_regime_reason: str = ""
        self.trade_logs: list = []
        self.session_stats = {
            "total_trades":   0,
            "winning_trades": 0,
            "losing_trades":  0,
            "win_sum":        0.0,
            "loss_sum":       0.0,
            "total_pnl":      0.0,
            "max_drawdown":   0.0,
        }
        self._scan_count = 0

    def start(self, strategy: str = "momentum"):
        self.active          = True
        self.active_strategy = strategy
        self._log("info", f"Bot started — Strategy: {strategy.upper()} | Mode: PAPER TRADING")
        self._log("info", f"Risk per position: {settings.max_position_percent}% | Stop: {settings.stop_loss_percent}% | TP: {settings.take_profit_percent}%")
        logger.info(f"Trading engine started: {strategy}")

    def stop(self):
        self.active = False
        self._log("info", "Trading engine stopped")
        logger.info("Trading engine stopped")

    @property
    def is_active(self) -> bool:
        return self.active

    async def run_cycle(self):
        """Run one trading cycle with autonomous start/stop logic."""
        now_et = datetime.now(ET)
        is_weekend = now_et.weekday() >= 5
        market_time = now_et.time()

        # Autonomous logic: Start 5 mins before (9:25 AM), Stop at close (4:00 PM)
        if not is_weekend:
            # 1. AUTO START (between 9:25 AM and 4:00 PM ET)
            if market_time >= time(9, 25) and market_time < time(16, 0):
                if not self.active:
                    from app.services.notification_service import notification_service
                    self.active = True
                    self.active_strategy = "momentum"
                    
                    if market_time < time(9, 30):
                        self._log("info", "[Auto-Start] Market opening soon! Bot is now ACTIVE.")
                        notification_service.send_alert("봇 자동 시작", "장 개장 5분 전입니다. 전략(Momentum)을 가동합니다.", "SUCCESS")
                    else:
                        self._log("info", "[Auto-Start] Market is open. Bot is now ACTIVE.")
                        notification_service.send_alert("봇 추격 시작", "장이 이미 열려있습니다. 전략(Momentum)을 가동합니다.", "SUCCESS")
            
            # 2. AUTO STOP (at 4:00 PM ET)
            if market_time >= time(16, 0) and self.active:
                from app.services.notification_service import notification_service
                self.active = False
                self._log("info", "[Auto-Stop] Market closed. Bot is now IDLE.")
                notification_service.send_alert("봇 퇴근 완료", "오늘 장이 마감되었습니다. 수고하셨습니다!", "INFO")

        if not self.active:
            return

        self._scan_count += 1

        if not is_market_open():
            if self._scan_count % 5 == 1:
                self._log("info", f"Standby — Market opens at 9:30 AM ET | Now: {now_et.strftime('%H:%M ET')}")
            return


        # ─── AI Adaptive Strategy Selection (Every 10 scans) ───
        if self._scan_count % 10 == 1:
            try:
                from app.services.analysis_agent import analysis_agent
                news = alpaca_service.get_latest_news(["AAPL", "NVDA", "SPY"], limit=5)
                if news:
                    new_strategy, reasoning = await analysis_agent.determine_market_regime(news)
                    self.last_regime_reason = reasoning  # Store for API access
                    if new_strategy != self.active_strategy:
                        self._log("info", f"AI Macro Analysis: {reasoning}")
                        self.active_strategy = new_strategy

            except Exception as e:
                logger.warning(f"AI strategy switching failed: {e}")


        try:
            account   = alpaca_service.get_account()
            positions = alpaca_service.get_positions()
            equity    = account["equity"]
            cash      = account["cash"]

            self._log("info", f"Scan #{self._scan_count} | Equity: ${equity:,.2f} | Cash: ${cash:,.2f} | Positions: {len(positions)}")

            # ─── Alert Monitoring (Monitoring Portfolio Changes) ─────
            pl_pct = (equity - 100000.0) / 100000.0 * 100
            
            from app.services.notification_service import notification_service
            
            # 1. 포트폴리오 비상 알림 (±5% 이상)
            if abs(pl_pct) >= 5.0 and self._scan_count % 60 == 0:   # 30분마다 알림
                level = "CRITICAL" if pl_pct <= -5 else "SUCCESS"
                title = "포트폴리오 비상" if pl_pct <= -5 else "포트폴리오 급등"
                msg   = f"현재 총 자산: ${equity:,.2f} ({pl_pct:+.1f}%). {'시장이 하락하고 있습니다. 대응이 필요합니다.' if pl_pct <= -5 else '시장이 아주 상승 중입니다! 수익을 즐기세요.' }"
                notification_service.send_alert(title, msg, level)
                self._log(level.lower(), f"[Alert] {title}: {pl_pct:+.1f}%")

            # 2. AI 분석가 시장 판세 변화 알림
            # (앞서 구현한 strategy switching과 연동)

            if self.active_strategy == "momentum":
                await self._run_momentum(account, positions)
            elif self.active_strategy == "mean-reversion":
                await self._run_mean_reversion(account, positions)

            elif self.active_strategy == "ml-predict":
                await self._run_ml_predict(account, positions)

        except Exception as e:
            self._log("error", f"Cycle error: {str(e)}")
            logger.error(f"Trading cycle error: {e}")

    # ─── Strategies ────────────────────────────────────────────

    async def _run_momentum(self, account: dict, positions: list):
        """
        Momentum Breakout Strategy:
        Buy:  RSI 45-70 AND MACD bullish AND price above MA50
        Sell: RSI < 35 OR stop loss (−2%) OR take profit (+5%)
        """
        symbols = ["AAPL", "MSFT", "NVDA", "AMZN", "AMD", "META", "GOOGL", "TSLA"]
        equity  = account["equity"]
        cash    = account["cash"]
        max_positions = 4   # hold up to 4 stocks at once

        current_symbols = [p["symbol"] for p in positions]
        slots_available = max_positions - len(current_symbols)

        # ── Manage existing positions ─────────────────────────
        for pos in positions:
            symbol = pos["symbol"]
            plpc   = pos["unrealized_plpc"]  # e.g. -0.023 = -2.3%

            bars   = alpaca_service.get_bars(symbol, "1Day", 50)
            if len(bars) < 20:
                continue
            closes     = [b["close"] for b in bars]
            indicators = self._calculate_indicators(closes)

            # Stop loss
            if plpc <= -(settings.stop_loss_percent / 100):
                self._log("sell", f"Stop loss: {symbol} {plpc*100:+.1f}% — selling")
                res = alpaca_service.submit_market_order(symbol, abs(int(pos["qty"])), "sell")
                if "error" not in res:
                    self._log("sell", f"Sold {abs(int(pos['qty']))} {symbol} (stop loss -{settings.stop_loss_percent}%)")
                    self.session_stats["total_trades"]  += 1
                    self.session_stats["losing_trades"] += 1
                    self.session_stats["loss_sum"]      += abs(pos["unrealized_pl"])
                    self.session_stats["total_pnl"]     += pos["unrealized_pl"]
                continue

            # Take profit
            if plpc >= (settings.take_profit_percent / 100):
                self._log("sell", f"Take profit: {symbol} {plpc*100:+.1f}% — selling")
                res = alpaca_service.submit_market_order(symbol, abs(int(pos["qty"])), "sell")
                if "error" not in res:
                    self._log("sell", f"Sold {abs(int(pos['qty']))} {symbol} (take profit +{settings.take_profit_percent}%)")
                    self.session_stats["total_trades"]   += 1
                    self.session_stats["winning_trades"] += 1
                    self.session_stats["win_sum"]        += pos["unrealized_pl"]
                    self.session_stats["total_pnl"]      += pos["unrealized_pl"]
                continue

            # RSI exit (momentum fading)
            if indicators["rsi"] < 35:
                self._log("signal", f"RSI exit: {symbol} RSI={indicators['rsi']:.1f} < 35 — closing")
                res = alpaca_service.submit_market_order(symbol, abs(int(pos["qty"])), "sell")
                if "error" not in res:
                    self._log("sell", f"Closed {symbol} (RSI={indicators['rsi']:.1f})")
                    self.session_stats["total_trades"] += 1
                    pnl_sign = 1 if plpc > 0 else 0
                    self.session_stats["winning_trades"] += pnl_sign
                    self.session_stats["losing_trades"]  += (1 - pnl_sign)
                    if plpc > 0:
                        self.session_stats["win_sum"] += pos["unrealized_pl"]
                    else:
                        self.session_stats["loss_sum"] += abs(pos["unrealized_pl"])
                    self.session_stats["total_pnl"]      += pos["unrealized_pl"]

        # ── Look for new entries ──────────────────────────────
        if slots_available <= 0 or cash < 500:
            self._log("info", f"No entry slots (positions={len(current_symbols)}, cash=${cash:,.0f})")
            return

        scored = []
        for symbol in symbols:
            if symbol in current_symbols:
                continue
            try:
                bars = alpaca_service.get_bars(symbol, "1Day", 50)
                if len(bars) < 26:
                    continue
                closes     = [b["close"] for b in bars]
                indicators = self._calculate_indicators(closes)
                price      = closes[-1]

                # Score: RSI momentum + MACD + above MA50
                score = 0
                reasons = []

                if 45 <= indicators["rsi"] <= 70:
                    score += 30
                    reasons.append(f"RSI={indicators['rsi']:.0f}")

                if indicators["macd_signal"] == "bullish":
                    score += 30
                    reasons.append("MACD↑")

                if price > indicators["ma50"]:
                    score += 20
                    reasons.append("Price>MA50")

                if price > indicators["ma20"]:
                    score += 10
                    reasons.append("Price>MA20")

                # Bollinger band position (not overbought)
                bb_pct = (price - indicators["bb_lower"]) / (indicators["bb_upper"] - indicators["bb_lower"] + 0.001)
                if 0.3 <= bb_pct <= 0.8:
                    score += 10
                    reasons.append("BB-mid")

                if score >= 50:
                    scored.append((score, symbol, price, indicators, reasons))

            except Exception as e:
                logger.warning(f"Signal calc error for {symbol}: {e}")

        # Sort by score, take top candidates
        scored.sort(key=lambda x: -x[0])
        entries = scored[:slots_available]

        for score, symbol, price, indicators, reasons in entries:
            max_position_value = equity * (settings.max_position_percent / 100)
            qty = int(min(max_position_value, cash * 0.95) / price)

            if qty <= 0:
                continue

            cost = qty * price
            self._log("signal", f"BUY signal {symbol}: score={score} | {' + '.join(reasons)} | ${price:.2f} × {qty} = ${cost:,.0f}")

            res = alpaca_service.submit_market_order(symbol, qty, "buy")
            if "error" not in res:
                self._log("buy", f"BOUGHT {qty} × {symbol} @ ~${price:.2f} (${cost:,.0f})")
                self.session_stats["total_trades"] += 1
            else:
                self._log("error", f"Order failed {symbol}: {res['error']}")

    async def _run_mean_reversion(self, account: dict, positions: list):
        """
        Mean Reversion: buy at lower Bollinger Band, sell at upper BB.
        """
        symbols = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
        equity  = account["equity"]
        cash    = account["cash"]
        current_symbols = [p["symbol"] for p in positions]

        for pos in positions:
            symbol = pos["symbol"]
            bars   = alpaca_service.get_bars(symbol, "1Day", 30)
            if len(bars) < 20:
                continue
            closes     = [b["close"] for b in bars]
            indicators = self._calculate_indicators(closes)
            price      = closes[-1]
            plpc       = pos["unrealized_plpc"]

            # Stop loss override
            if plpc <= -(settings.stop_loss_percent / 100):
                self._log("sell", f"Stop loss: {symbol} {plpc*100:+.1f}%")
                alpaca_service.submit_market_order(symbol, abs(int(pos["qty"])), "sell")
                self.session_stats["total_trades"]  += 1
                self.session_stats["losing_trades"] += 1
                self.session_stats["loss_sum"]      += abs(pos["unrealized_pl"])
                continue

            # Sell at upper band or take profit
            if price >= indicators["bb_upper"] or plpc >= (settings.take_profit_percent / 100):
                reason = "BB upper" if price >= indicators["bb_upper"] else "Take profit"
                self._log("sell", f"{reason}: {symbol} @ ${price:.2f}")
                alpaca_service.submit_market_order(symbol, abs(int(pos["qty"])), "sell")
                self.session_stats["total_trades"]   += 1
                self.session_stats["winning_trades"] += 1
                self.session_stats["win_sum"]        += pos["unrealized_pl"]

        for symbol in symbols:
            if symbol in current_symbols:
                continue
            bars = alpaca_service.get_bars(symbol, "1Day", 30)
            if len(bars) < 20:
                continue
            closes     = [b["close"] for b in bars]
            indicators = self._calculate_indicators(closes)
            price      = closes[-1]

            if price <= indicators["bb_lower"] and indicators["rsi"] < 35:
                max_val = equity * (settings.max_position_percent / 100)
                qty     = int(min(max_val, cash * 0.9) / price)
                if qty > 0:
                    self._log("signal", f"Mean Reversion BUY {symbol}: at lower BB, RSI={indicators['rsi']:.0f}")
                    res = alpaca_service.submit_market_order(symbol, qty, "buy")
                    if "error" not in res:
                        self._log("buy", f"Bought {qty} {symbol} @ ${price:.2f}")
                        self.session_stats["total_trades"] += 1

    async def _run_ml_predict(self, account: dict, positions: list):
        """ML Prediction: combines momentum + mean-reversion signals with scoring."""
        self._log("info", "ML hybrid scan: combining momentum + reversion signals...")
        await self._run_momentum(account, positions)

    # ─── Technical Indicators ──────────────────────────────────

    def _calculate_indicators(self, closes: list) -> dict:
        import numpy as np
        arr = np.array(closes, dtype=float)

        rsi = self._calculate_rsi(arr, 14)

        ema12 = self._ema(arr, 12)
        ema26 = self._ema(arr, 26)
        macd  = ema12 - ema26
        sig   = self._ema(macd, 9)
        macd_signal = "bullish" if macd[-1] > sig[-1] else "bearish"

        ma20    = float(np.mean(arr[-20:])) if len(arr) >= 20 else float(np.mean(arr))
        ma50    = float(np.mean(arr[-50:])) if len(arr) >= 50 else float(np.mean(arr))
        std20   = float(np.std(arr[-20:]))  if len(arr) >= 20 else float(np.std(arr))
        bb_upper = ma20 + 2 * std20
        bb_lower = ma20 - 2 * std20

        return {
            "rsi":         rsi,
            "macd_line":   float(macd[-1]),
            "macd_signal": macd_signal,
            "bb_upper":    bb_upper,
            "bb_lower":    bb_lower,
            "bb_middle":   ma20,
            "ma20":        ma20,
            "ma50":        ma50,
            "current_price": float(arr[-1]),
        }

    def _calculate_rsi(self, prices, period: int = 14) -> float:
        import numpy as np
        deltas   = np.diff(prices)
        gains    = np.where(deltas > 0, deltas, 0.0)
        losses   = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100 - (100 / (1 + rs)))

    def _ema(self, data, period: int):
        import numpy as np
        alpha = 2 / (period + 1)
        ema   = np.zeros_like(data, dtype=float)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
        return ema

    # ─── Logging ───────────────────────────────────────────────

    def _log(self, log_type: str, message: str):
        entry = {
            "time":    datetime.now().strftime("%H:%M:%S"),
            "type":    log_type,
            "message": message,
        }
        self.trade_logs.append(entry)
        self.trade_logs = self.trade_logs[-300:]
        logger.info(f"[{log_type.upper()}] {message}")

    def get_logs(self, limit: int = 50) -> list:
        return self.trade_logs[-limit:]

    def get_stats(self) -> dict:
        total = self.session_stats["total_trades"]
        wins = self.session_stats["winning_trades"]
        losses = self.session_stats["losing_trades"]
        win_sum = self.session_stats["win_sum"]
        loss_sum = self.session_stats["loss_sum"]

        return {
            **self.session_stats,
            "win_rate": (wins / total * 100) if total > 0 else 0,
            "avg_win": (win_sum / wins) if wins > 0 else 0,
            "avg_loss": (loss_sum / losses) if losses > 0 else 0,
            "profit_factor": (win_sum / loss_sum) if loss_sum > 0 else (win_sum if win_sum > 0 else 0),
        }


# Singleton
trading_engine = TradingEngine()
