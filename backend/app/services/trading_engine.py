"""
TradeSense - Trading Engine v3
Cash Account Micro-Scalping Strategy
─────────────────────────────────────
$3,000 시작 → 매일 +1% 복리 → 한 달 후 $4,000 목표
캐시 어카운트: PDT 면제, GFV 방지 로직 내장
"""
import logging
import asyncio
from datetime import datetime, time, date, timedelta
import pytz
from typing import Optional
from app.core.config import settings
from app.services.alpaca_service import alpaca_service

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


def is_market_open() -> bool:
    """Check if US stock market is currently open."""
    now_et = datetime.now(ET)
    if now_et.weekday() >= 5:
        return False
    market_open  = time(9, 30)
    market_close = time(16, 0)
    return market_open <= now_et.time() <= market_close


class TradingEngine:
    """Cash Account Micro-Scalp Engine with GFV prevention."""

    # ─── Liquid scalping candidates (tight spreads, high volume) ───
    SCALP_UNIVERSE = [
        "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AMD", "TSLA",
        "SPY", "QQQ", "INTC", "NFLX", "AVGO", "CRM", "UBER",
    ]

    def __init__(self):
        self.active           = False
        self.active_strategy: Optional[str] = None
        self.last_regime_reason: str = ""

        # AI-driven focus (can override SCALP_UNIVERSE)
        self.focus_symbols: list = list(self.SCALP_UNIVERSE[:8])
        self.focus_sectors: list = ["tech_ai", "tech_software"]

        # ─── GFV Prevention (Cash Account) ─────────────────────
        self._unsettled_funds: float = 0.0
        self._unsettled_date: Optional[date] = None
        self._positions_bought_with_unsettled: set = set()  # symbols bought with unsettled $

        # ─── Daily P&L Tracking ────────────────────────────────
        self._trading_date: Optional[date] = None
        self._daily_pnl: float = 0.0
        self._daily_trades: int = 0
        self._daily_target_reached: bool = False
        self._daily_loss_limit_hit: bool = False
        self._day_start_equity: float = settings.initial_capital

        # ─── Regime / UI data ─────────────────────────────────
        self.regime_data: dict = {
            "strategy": "scalp",
            "reasoning": "Cash account micro-scalp: $3,000 → 매일 +1% 복리",
            "risk_level": settings.risk_level,
            "max_position_percent": settings.max_position_percent,
            "stop_loss_percent": settings.stop_loss_percent,
            "focus_sectors": self.focus_sectors,
            "focus_symbols": self.focus_symbols,
            "daily_target": f"+{settings.daily_target_percent}%",
            "daily_pnl": "$0.00",
            "account_type": settings.account_type,
            "timestamp": datetime.now().strftime("%b %d, %Y, %-I:%M%p")
        }

        # ─── Session stats ────────────────────────────────────
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
        self._v3_cleanup_done = False  # Flag: have we cleaned up legacy positions?

    # ─── Control ──────────────────────────────────────────────

    def start(self, strategy: str = "scalp", stop_loss: Optional[float] = None, take_profit: Optional[float] = None, max_position: Optional[float] = None):
        self.active          = True
        self.active_strategy = strategy
        self.regime_data["strategy"] = strategy
        self.regime_data["timestamp"] = datetime.now().strftime("%b %d, %Y, %-I:%M%p")

        # Apply custom settings if provided
        if stop_loss is not None:
            settings.stop_loss_percent = stop_loss
        if take_profit is not None:
            settings.take_profit_percent = take_profit
        if max_position is not None:
            settings.max_position_percent = max_position

        self._log("info", f"🚀 Bot started — Strategy: MICRO-SCALP | Capital: ${settings.initial_capital:,.0f}")
        self._log("info", f"📋 Cash Account | Target: +{settings.daily_target_percent}%/day | Stop: -{settings.daily_loss_limit_percent}%/day")
        self._log("info", f"📊 Position: {settings.max_position_percent}% | TP: +{settings.take_profit_percent}% | SL: -{settings.stop_loss_percent}%")
        logger.info(f"Trading engine started: {strategy} (SL: {settings.stop_loss_percent}%, TP: {settings.take_profit_percent}%)")

    def stop(self):
        self.active = False
        self._log("info", "Trading engine stopped")
        logger.info("Trading engine stopped")

    @property
    def is_active(self) -> bool:
        return self.active

    # ─── Main Loop ────────────────────────────────────────────

    async def run_cycle(self):
        """Run one trading cycle."""
        now_et = datetime.now(ET)
        is_weekend = now_et.weekday() >= 5
        market_time = now_et.time()
        today = now_et.date()

        # ─── New Day Reset ────────────────────────────────────
        if self._trading_date != today:
            self._reset_daily(today)

        # ─── Auto Start/Stop ─────────────────────────────────
        if not is_weekend:
            if market_time >= time(9, 25) and market_time < time(16, 0):
                if not self.active:
                    from app.services.notification_service import notification_service
                    self.active = True
                    self.active_strategy = "scalp"
                    self._log("info", "[Auto-Start] Market opening — Scalp bot ACTIVE")
                    notification_service.send_alert(
                        "🚀 스캘핑 봇 시작",
                        f"오늘 목표: +{settings.daily_target_percent}% (${self._day_start_equity * settings.daily_target_percent / 100:,.0f})",
                        "SUCCESS"
                    )

            if market_time >= time(16, 0) and self.active:
                from app.services.notification_service import notification_service
                self.active = False
                self._log("info", f"[Auto-Stop] Market closed | Today P&L: ${self._daily_pnl:+,.2f} ({self._daily_trades} trades)")
                notification_service.send_alert(
                    "📊 오늘의 성적표",
                    f"P&L: ${self._daily_pnl:+,.2f} | Trades: {self._daily_trades}",
                    "SUCCESS" if self._daily_pnl >= 0 else "CRITICAL"
                )

        if not self.active:
            return

        self._scan_count += 1

        if not is_market_open():
            if self._scan_count % 5 == 1:
                self._log("info", f"Standby — Market opens at 9:30 AM ET | Now: {now_et.strftime('%H:%M ET')}")
            return

        # ─── Check daily limits ───────────────────────────────
        if self._daily_loss_limit_hit:
            if self._scan_count % 10 == 1:
                self._log("info", f"⛔ Daily loss limit hit (${self._daily_pnl:+,.2f}). No more trades today.")
            return

        # ─── AI Adaptive (every 10 scans) ─────────────────────
        if self._scan_count % 10 == 1:
            await self._ai_regime_check()

        # ─── One-time cleanup of legacy positions ─────────────
        if not self._v3_cleanup_done:
            await self._cleanup_legacy_positions()
            self._v3_cleanup_done = True
            return  # Skip this cycle, start fresh next cycle

        # ─── Execute Strategy ─────────────────────────────────
        try:
            account   = alpaca_service.get_account()
            positions = alpaca_service.get_positions()
            equity    = account["equity"]
            cash      = account["cash"]

            # Update daily P&L
            self._daily_pnl = equity - self._day_start_equity
            daily_pnl_pct = (self._daily_pnl / self._day_start_equity) * 100

            # Update regime_data for UI
            self.regime_data["daily_pnl"] = f"${self._daily_pnl:+,.2f} ({daily_pnl_pct:+.2f}%)"

            self._log("info",
                f"Scan #{self._scan_count} | Equity: ${equity:,.2f} | "
                f"Daily P&L: ${self._daily_pnl:+,.2f} ({daily_pnl_pct:+.2f}%) | "
                f"Positions: {len(positions)} | Trades: {self._daily_trades}")

            # Check daily loss limit
            if daily_pnl_pct <= -settings.daily_loss_limit_percent:
                self._daily_loss_limit_hit = True
                from app.services.notification_service import notification_service
                self._log("info", f"⛔ DAILY LOSS LIMIT: {daily_pnl_pct:.2f}% — stopping trades for today")
                notification_service.send_alert(
                    "⛔ 일일 손실 한도 도달",
                    f"P&L: ${self._daily_pnl:+,.2f} ({daily_pnl_pct:+.2f}%)\n오늘은 더 이상 매매하지 않습니다.",
                    "CRITICAL"
                )
                return

            # Check daily target
            if daily_pnl_pct >= settings.daily_target_percent and not self._daily_target_reached:
                self._daily_target_reached = True
                from app.services.notification_service import notification_service
                self._log("info", f"🎯 DAILY TARGET REACHED: +{daily_pnl_pct:.2f}% — reducing aggressiveness")
                notification_service.send_alert(
                    "🎯 일일 목표 달성!",
                    f"P&L: ${self._daily_pnl:+,.2f} (+{daily_pnl_pct:.2f}%)\n공격성을 줄이고 수익을 보호합니다.",
                    "SUCCESS"
                )

            # Run scalp strategy
            await self._run_scalp(account, positions)

        except Exception as e:
            self._log("error", f"Cycle error: {str(e)}")
            logger.error(f"Trading cycle error: {e}")

    # ── Legacy Position Cleanup ─────────────────────────────────

    async def _cleanup_legacy_positions(self):
        """Sell ALL existing positions from old strategy. V3 starts with a clean slate."""
        try:
            positions = alpaca_service.get_positions()
            if not positions:
                self._log("info", "✅ No legacy positions — clean start!")
                return

            self._log("info", f"🧹 Cleaning up {len(positions)} legacy positions from old strategy...")

            for pos in positions:
                symbol = pos["symbol"]
                qty = abs(int(pos["qty"]))
                if qty <= 0:
                    continue
                self._log("info", f"  Selling {qty}x {symbol} (legacy cleanup)")
                res = alpaca_service.submit_market_order(symbol, qty, "sell")
                if "error" in res:
                    self._log("error", f"  Failed to close {symbol}: {res['error']}")
                else:
                    self._log("info", f"  ✅ Closed {symbol}")

            self._log("info", "🧹 Legacy cleanup complete — ready for $3,000 scalping!")

        except Exception as e:
            self._log("error", f"Legacy cleanup error: {e}")
            logger.error(f"Legacy cleanup error: {e}")

    # ─── Daily Reset ──────────────────────────────────────────

    def _reset_daily(self, today: date):
        """Reset daily tracking for a new trading day."""
        # Settle yesterday's unsettled funds
        if self._unsettled_date and self._unsettled_date < today:
            self._log("info", f"💰 Settled ${self._unsettled_funds:,.2f} from {self._unsettled_date}")
            self._unsettled_funds = 0.0
            self._unsettled_date = None
            self._positions_bought_with_unsettled.clear()

        self._trading_date = today
        self._daily_pnl = 0.0
        self._daily_trades = 0
        self._daily_target_reached = False
        self._daily_loss_limit_hit = False

        # Get current equity as day start
        try:
            account = alpaca_service.get_account()
            self._day_start_equity = account["equity"]
        except Exception:
            self._day_start_equity = settings.initial_capital

        self._log("info", f"📅 New trading day: {today} | Start equity: ${self._day_start_equity:,.2f}")
        self._log("info", f"🎯 Today's target: +${self._day_start_equity * settings.daily_target_percent / 100:,.2f} (+{settings.daily_target_percent}%)")

    # ─── GFV Prevention ───────────────────────────────────────

    def _get_settled_cash(self, total_cash: float) -> float:
        """Return only settled (available) cash for new buys."""
        settled = total_cash - self._unsettled_funds
        return max(settled, 0.0)

    def _record_sell(self, proceeds: float):
        """After a sell, mark proceeds as unsettled (T+1)."""
        today = datetime.now(ET).date()
        if self._unsettled_date != today:
            # New day of unsettled funds
            self._unsettled_funds = proceeds
            self._unsettled_date = today
        else:
            self._unsettled_funds += proceeds

    def _can_sell(self, symbol: str) -> bool:
        """Check if we can sell this position without causing a GFV."""
        # If we bought with unsettled funds, can't sell until settled
        if symbol in self._positions_bought_with_unsettled:
            self._log("info", f"⚠️ GFV prevention: {symbol} bought with unsettled funds, holding until settlement")
            return False
        return True

    # ─── AI Regime Check ──────────────────────────────────────

    async def _ai_regime_check(self):
        """Use AI to analyze news and adjust focus symbols."""
        try:
            from app.services.analysis_agent import analysis_agent
            news = alpaca_service.get_latest_news(
                ["AAPL", "NVDA", "SPY", "QQQ", "GLD", "USO"], limit=10
            )
            if news:
                regime = await analysis_agent.determine_market_regime(news)
                self.last_regime_reason = regime["reasoning"]

                old_strat = self.active_strategy
                old_risk = settings.risk_level

                # Apply focus symbols from AI
                new_symbols = regime.get("focus_symbols", self.focus_symbols)
                new_sectors = regime.get("focus_sectors", self.focus_sectors)
                if new_symbols != self.focus_symbols:
                    self._log("info", f"🔄 AI Focus Shift: {', '.join(new_sectors)} → {', '.join(new_symbols[:5])}...")
                    self.focus_symbols = new_symbols
                    self.focus_sectors = new_sectors

                # Apply risk settings (but keep scalp-appropriate bounds)
                settings.risk_level = regime["risk_level"]
                ai_sl = float(regime.get("stop_loss_percent", 0.3))
                settings.stop_loss_percent = max(0.2, min(ai_sl, 1.0))  # Clamp 0.2-1.0% for scalping

                ai_pos = float(regime.get("max_position_percent", 15))
                settings.max_position_percent = max(10, min(ai_pos, 20))  # Clamp 10-20%

                self.regime_data = {
                    **regime,
                    "prev_strategy": old_strat,
                    "prev_risk_level": old_risk,
                    "daily_target": f"+{settings.daily_target_percent}%",
                    "daily_pnl": self.regime_data.get("daily_pnl", "$0.00"),
                    "account_type": settings.account_type,
                    "timestamp": datetime.now().strftime("%b %d, %Y, %-I:%M%p")
                }

                if old_risk != settings.risk_level:
                    from app.services.notification_service import notification_service
                    notification_service.send_alert(
                        "🔄 Market Regime Update",
                        f"Risk: {old_risk} → {settings.risk_level}\nReason: {regime['reasoning']}",
                        "INFO"
                    )

        except Exception as e:
            logger.warning(f"AI regime check failed: {e}")

    # ─── Scalping Strategy ────────────────────────────────────

    async def _run_scalp(self, account: dict, positions: list):
        """
        Micro-Scalp Strategy (5-min bars):
        ─ Buy:  RSI bounce + VWAP support + volume spike
        ─ Sell:  +0.5~1.0% take profit  OR  -0.3% stop loss
        ─ GFV:   Only buy with settled cash
        """
        equity  = account["equity"]
        cash    = account["cash"]
        settled = self._get_settled_cash(cash)
        max_positions = 4

        current_symbols = [p["symbol"] for p in positions]
        slots_available = max_positions - len(current_symbols)

        # Raise entry threshold if daily target already reached
        entry_score_threshold = 50 if not self._daily_target_reached else 70

        # ── 1. Manage existing positions (tight scalp exits) ──
        for pos in positions:
            symbol = pos["symbol"]
            plpc   = pos["unrealized_plpc"]   # e.g. -0.003 = -0.3%
            pl_usd = pos["unrealized_pl"]

            # GFV check: can we sell this?
            if not self._can_sell(symbol):
                continue

            # Stop loss (tight for scalping)
            if plpc <= -(settings.stop_loss_percent / 100):
                self._log("sell", f"🔴 STOP LOSS: {symbol} {plpc*100:+.2f}% (${pl_usd:+,.2f})")
                res = alpaca_service.submit_market_order(symbol, abs(int(pos["qty"])), "sell")
                if "error" not in res:
                    proceeds = abs(int(pos["qty"])) * pos.get("current_price", pos.get("avg_entry_price", 0))
                    self._record_sell(proceeds)
                    self._daily_trades += 1
                    self.session_stats["total_trades"]  += 1
                    self.session_stats["losing_trades"] += 1
                    self.session_stats["loss_sum"]      += abs(pl_usd)
                    self.session_stats["total_pnl"]     += pl_usd
                continue

            # Take profit
            if plpc >= (settings.take_profit_percent / 100):
                self._log("sell", f"🟢 TAKE PROFIT: {symbol} {plpc*100:+.2f}% (${pl_usd:+,.2f})")
                res = alpaca_service.submit_market_order(symbol, abs(int(pos["qty"])), "sell")
                if "error" not in res:
                    proceeds = abs(int(pos["qty"])) * pos.get("current_price", pos.get("avg_entry_price", 0))
                    self._record_sell(proceeds)
                    self._daily_trades += 1
                    self.session_stats["total_trades"]   += 1
                    self.session_stats["winning_trades"] += 1
                    self.session_stats["win_sum"]        += pl_usd
                    self.session_stats["total_pnl"]      += pl_usd
                continue

            # Trailing stop: if we were up but now falling back toward breakeven
            if 0.003 <= plpc < 0.005:
                self._log("sell", f"🟡 TRAIL EXIT: {symbol} {plpc*100:+.2f}%")
                res = alpaca_service.submit_market_order(symbol, abs(int(pos["qty"])), "sell")
                if "error" not in res:
                    proceeds = abs(int(pos["qty"])) * pos.get("current_price", pos.get("avg_entry_price", 0))
                    self._record_sell(proceeds)
                    self._daily_trades += 1
                    self.session_stats["total_trades"]   += 1
                    if plpc > 0:
                        self.session_stats["winning_trades"] += 1
                        self.session_stats["win_sum"]        += pl_usd
                    else:
                        self.session_stats["losing_trades"]  += 1
                        self.session_stats["loss_sum"]       += abs(pl_usd)
                    self.session_stats["total_pnl"]      += pl_usd

        # ── 2. Check if we can enter new positions ────────────
        if slots_available <= 0:
            return
        if settled < 100:  # Need at least $100 settled cash
            self._log("info", f"💤 Settled cash too low: ${settled:,.2f} (unsettled: ${self._unsettled_funds:,.2f})")
            return
        # Unrestricted scalping: Trading count limit removed as per user request

        # ── 3. Scan for scalp entries ─────────────────────────
        symbols_to_scan = self.focus_symbols[:10]  # AI-selected focus
        scored = []

        for symbol in symbols_to_scan:
            if symbol in current_symbols:
                continue
            try:
                # Use 5-min bars for scalp signals
                bars = alpaca_service.get_bars(symbol, "5Min", 50)
                if len(bars) < 20:
                    # Fallback to daily bars
                    bars = alpaca_service.get_bars(symbol, "1Day", 30)
                    if len(bars) < 14:
                        continue

                closes  = [b["close"] for b in bars]
                volumes = [b.get("volume", 0) for b in bars]
                indicators = self._calculate_indicators(closes)
                price = closes[-1]

                # ── Score the entry signal ─────────────────
                score = 0
                reasons = []

                # RSI oversold bounce (strongest scalp signal)
                if indicators["rsi"] < 35:
                    score += 30
                    reasons.append(f"RSI↓{indicators['rsi']:.0f}")
                elif 35 <= indicators["rsi"] <= 45:
                    score += 15
                    reasons.append(f"RSI={indicators['rsi']:.0f}")

                # MACD bullish crossover
                if indicators["macd_signal"] == "bullish":
                    score += 25
                    reasons.append("MACD↑")

                # Bollinger Band: near lower band = buy zone
                if indicators["bb_lower"] > 0:
                    bb_pct = (price - indicators["bb_lower"]) / (indicators["bb_upper"] - indicators["bb_lower"] + 0.001)
                    if bb_pct < 0.2:
                        score += 25
                        reasons.append("BB-low")
                    elif bb_pct < 0.4:
                        score += 10
                        reasons.append("BB-mid")

                # Price above short MA (micro trend up)
                if len(closes) >= 10:
                    ma10 = sum(closes[-10:]) / 10
                    if price > ma10:
                        score += 10
                        reasons.append("P>MA10")

                # Volume surge (2x avg = institutional interest)
                if volumes and len(volumes) >= 10:
                    avg_vol = sum(volumes[-10:]) / 10
                    if avg_vol > 0 and volumes[-1] > avg_vol * 2:
                        score += 15
                        reasons.append("Vol🔥")

                if score >= entry_score_threshold:
                    scored.append((score, symbol, price, indicators, reasons))

            except Exception as e:
                logger.warning(f"Scan error for {symbol}: {e}")

        # ── 4. Execute top entries ────────────────────────────
        scored.sort(key=lambda x: -x[0])
        entries = scored[:slots_available]

        for score, symbol, price, indicators, reasons in entries:
            # Position sizing: max 15% of equity, only use settled cash
            max_position_value = equity * (settings.max_position_percent / 100)
            buy_power = min(max_position_value, settled * 0.95)
            qty = int(buy_power / price)

            if qty <= 0:
                continue

            cost = qty * price
            self._log("signal",
                f"📊 BUY signal {symbol}: score={score} | {' + '.join(reasons)} | "
                f"${price:.2f} × {qty} = ${cost:,.0f}")

            res = alpaca_service.submit_market_order(symbol, qty, "buy")
            if "error" not in res:
                self._log("buy", f"✅ BOUGHT {qty} × {symbol} @ ~${price:.2f} (${cost:,.0f})")
                self._daily_trades += 1
                self.session_stats["total_trades"] += 1
                settled -= cost  # Reduce available settled cash
            else:
                self._log("error", f"Order failed {symbol}: {res['error']}")

    # ─── Technical Indicators ──────────────────────────────────

    def _calculate_indicators(self, closes: list) -> dict:
        import numpy as np
        arr = np.array(closes, dtype=float)

        rsi = self._calculate_rsi(arr, 14)

        ema12 = self._ema(arr, 12)
        ema26 = self._ema(arr, 26) if len(arr) >= 26 else self._ema(arr, len(arr))
        macd  = ema12[:len(ema26)] - ema26 if len(ema12) >= len(ema26) else ema12 - ema26[:len(ema12)]
        sig   = self._ema(macd, 9) if len(macd) >= 9 else self._ema(macd, max(len(macd), 1))
        macd_signal = "bullish" if len(macd) > 0 and len(sig) > 0 and macd[-1] > sig[-1] else "bearish"

        n = min(20, len(arr))
        ma20    = float(np.mean(arr[-n:]))
        std20   = float(np.std(arr[-n:]))
        bb_upper = ma20 + 2 * std20
        bb_lower = ma20 - 2 * std20

        ma50 = float(np.mean(arr[-min(50, len(arr)):])) if len(arr) >= 10 else float(np.mean(arr))

        return {
            "rsi":         rsi,
            "macd_line":   float(macd[-1]) if len(macd) > 0 else 0,
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
        if len(prices) < 2:
            return 50.0
        deltas   = np.diff(prices)
        p = min(period, len(deltas))
        gains    = np.where(deltas[-p:] > 0, deltas[-p:], 0.0)
        losses   = np.where(deltas[-p:] < 0, -deltas[-p:], 0.0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100 - (100 / (1 + rs)))

    def _ema(self, data, period: int):
        import numpy as np
        if len(data) == 0:
            return np.array([0.0])
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
            "daily_pnl": self._daily_pnl,
            "daily_trades": self._daily_trades,
            "daily_target_reached": self._daily_target_reached,
            "settled_cash_available": self._get_settled_cash(0),  # approximate
        }


# Singleton
trading_engine = TradingEngine()
