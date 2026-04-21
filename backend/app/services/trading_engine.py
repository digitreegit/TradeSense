"""
TradeSense - Trading Engine v4
Cash-account micro-scalping with compliance, event, and regime guards.

Delegates:
- Compliance (GFV / free-riding / wash-sale / cooldowns) → self._compliance
- Macro regime score + universe tilt                    → regime_service
- Macro event / opening-auction blackout                → event_calendar
- Risk preset tables driven by regime score             → core.risk_presets
- Entry scoring (scalp + VWAP + ORB + EOD + news-fade)  → playbooks
- Marketable-limit orders + spread filter               → execution_service
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time
from typing import Optional

import pytz

from app.core.config import settings
from app.core.risk_presets import (
    RISK_PRESETS,
    is_halted_score,
    market_level_for_score,
    preset_for_score,
)
from app.services.alpaca_service import AlpacaService
from app.services.compliance_service import ComplianceService
from app.services.event_calendar import is_blackout, symbol_is_earnings_today
from app.services.execution_service import Executor, spread_info
from app.services.playbooks import combine as combine_playbooks
from app.services.regime_service import RegimeService

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

    # ─── Playbook metadata (shared with /trading/strategies route) ───
    PLAYBOOKS: list = [
        {
            "id": "scalp",
            "name": "Micro-Scalping v4",
            "description": "RSI/MACD/BB + volume surge on 5-min bars",
        },
        {
            "id": "vwap",
            "name": "VWAP Mean-Reversion",
            "description": "Fade deviations below VWAP during RTH",
        },
        {
            "id": "orb",
            "name": "Opening Range Breakout",
            "description": "Buy break above 9:30–9:35 range, valid until 11:00 ET",
        },
        {
            "id": "eod",
            "name": "End-of-Day Drift",
            "description": "Favor up-trending names into 15:50–15:58 close",
        },
        {
            "id": "news-fade",
            "name": "News Spike Fade",
            "description": "Fade exhaustion after AI-detected panic",
        },
    ]
    PLAYBOOK_IDS: list = [p["id"] for p in PLAYBOOKS]

    def __init__(self, alpaca: AlpacaService, compliance: ComplianceService):
        self._alpaca = alpaca
        self._compliance = compliance
        self._executor = Executor(alpaca)
        self._regime = RegimeService(alpaca)

        self.active           = False
        self.active_strategy: Optional[str] = None
        self.last_regime_reason: str = ""

        # Focus universe (AI + regime tilt can override)
        self.focus_symbols: list = list(self.SCALP_UNIVERSE[:8])
        self.focus_sectors: list = ["tech_ai", "tech_software"]

        # Daily tracking
        self._trading_date: Optional[date] = None
        self._daily_pnl: float = 0.0
        self._daily_trades: int = 0
        self._daily_target_reached: bool = False
        self._daily_loss_limit_hit: bool = False
        self._day_start_equity: float = settings.initial_capital

        # Per-position peaks for trailing stop high-water mark
        self._position_peaks: dict = {}

        # Current active risk preset (starts moderate)
        self._preset = RISK_PRESETS["moderate"]

        # Regime / UI data
        self.regime_data: dict = {
            "strategy": "scalp",
            "reasoning": "Cash-account micro-scalp: $3,000 → +1%/day compounding target",
            "risk_level": self._preset.level,
            "market_score": 50.0,
            "market_level": "NORMAL",
            "market_scores": {},
            "max_position_percent": self._preset.max_position_percent,
            "stop_loss_percent": self._preset.stop_loss_percent,
            "focus_sectors": self.focus_sectors,
            "focus_symbols": self.focus_symbols,
            "daily_target": f"+{self._preset.daily_target_percent}%",
            "daily_pnl": "$0.00",
            "account_type": settings.account_type,
            "blackout": False,
            "blackout_reason": "",
            "timestamp": datetime.now().strftime("%b %d, %Y, %-I:%M%p"),
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

        # ─── Playbook routing ────────────────────────────────
        # auto_playbooks=True → engine decides which playbooks participate
        # based on time-of-day / regime; user edits the MANUAL list instead,
        # which is only consulted when auto is OFF.
        self.auto_playbooks: bool = True
        self.manual_playbooks: list = ["scalp", "vwap", "orb", "eod"]
        self._last_active_playbooks: list = list(self.manual_playbooks)
        self._sync_regime_playbook_display()

    # ─── Control ──────────────────────────────────────────────

    def start(
        self,
        strategy: str = "scalp",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        max_position: Optional[float] = None,
        risk_level: Optional[str] = None,
    ):
        self.active          = True
        self.active_strategy = strategy
        self.regime_data["timestamp"] = datetime.now().strftime("%b %d, %Y, %-I:%M%p")
        self._sync_regime_playbook_display()

        if risk_level:
            from app.core.risk_presets import preset_for_level
            self._preset = preset_for_level(risk_level)

        # Overrides still allowed, but clamped to scalp-safe bounds.
        preset = self._preset
        if stop_loss is not None:
            preset = preset.__class__(
                **{**preset.as_dict(), "stop_loss_percent": max(0.1, min(stop_loss, 1.0))}
            )
        if take_profit is not None:
            preset = preset.__class__(
                **{**preset.as_dict(), "take_profit_percent": max(0.3, min(take_profit, 3.0))}
            )
        if max_position is not None:
            preset = preset.__class__(
                **{**preset.as_dict(), "max_position_percent": max(5.0, min(max_position, 25.0))}
            )
        self._preset = preset

        self._log(
            "info",
            f"🚀 Bot started — {preset.level.upper()} | Capital: ${settings.initial_capital:,.0f}",
        )
        self._log(
            "info",
            f"Target +{preset.daily_target_percent}% | Loss limit -{preset.daily_loss_limit_percent}% | "
            f"Pos {preset.max_position_percent}% × {preset.max_concurrent_positions} slots",
        )
        self._log(
            "info",
            f"SL -{preset.stop_loss_percent}% | TP +{preset.take_profit_percent}% | "
            f"Trail {preset.trailing_trigger_percent}% | Spread ≤ {preset.spread_filter_percent}%",
        )
        logger.info("Trading engine started: %s (preset=%s)", strategy, preset.level)

    def stop(self):
        self.active = False
        self._log("info", "Trading engine stopped")
        logger.info("Trading engine stopped")

    @property
    def is_active(self) -> bool:
        return self.active

    # ─── Playbook configuration ───────────────────────────────

    def get_playbook_config(self) -> dict:
        """Return current playbook routing state (for the API / UI)."""
        active = self._choose_active_playbooks(datetime.now(ET))
        return {
            "auto": self.auto_playbooks,
            "manual": list(self.manual_playbooks),
            "active": active,
            "playbooks": [
                {
                    **p,
                    "manual_enabled": p["id"] in self.manual_playbooks,
                    "active_now": p["id"] in active,
                }
                for p in self.PLAYBOOKS
            ],
        }

    def set_playbook_config(
        self,
        auto: Optional[bool] = None,
        manual: Optional[list] = None,
    ) -> dict:
        """Update AUTO flag and/or the manual enabled set. Unknown ids are ignored."""
        if auto is not None:
            self.auto_playbooks = bool(auto)
        if manual is not None:
            cleaned = [pid for pid in manual if pid in self.PLAYBOOK_IDS]
            self.manual_playbooks = cleaned
        if not self.auto_playbooks and not self.manual_playbooks:
            self.manual_playbooks = ["scalp"]
            self._log(
                "info",
                "Manual playbook list was empty — defaulted to ['scalp'] to keep the bot functional.",
            )
        self._log(
            "info",
            f"Playbooks updated — AUTO={self.auto_playbooks} | "
            f"manual={','.join(self.manual_playbooks) or '∅'}",
        )
        self._sync_regime_playbook_display()
        return self.get_playbook_config()

    def _choose_active_playbooks(self, now_et: datetime) -> list:
        """AUTO → time-of-day + regime driven routing.
        MANUAL → respect whatever the user ticked."""
        if not self.auto_playbooks:
            return list(self.manual_playbooks)

        t = now_et.time()
        score = float(self.regime_data.get("market_score", 50.0) or 50.0)
        news = float(self.regime_data.get("news_score", 0.0) or 0.0)

        active: list = []

        # Opening auction window (9:30 – 9:35) already blacked out upstream,
        # but as soon as the range prints we enable ORB until late morning.
        if time(9, 35) <= t < time(11, 0):
            active.append("orb")

        # VWAP mean-reversion is most useful after the first impulse.
        if time(10, 0) <= t < time(15, 30):
            active.append("vwap")

        # Core scalp across RTH except the very last minutes where spreads widen.
        if time(9, 35) <= t < time(15, 45):
            active.append("scalp")

        # EOD drift into the close window.
        if time(15, 30) <= t < time(15, 58):
            active.append("eod")

        # News-fade is only trusted when a strong panic signal is in regime.
        if news <= -0.6:
            active.append("news-fade")

        # In clearly risk-off regimes, fall back to news-fade only.
        if score < 25:
            active = [p for p in active if p in ("news-fade",)] or ["news-fade"]

        # If nothing matched (e.g. pre-market / after-hours), keep at least the scalp.
        if not active:
            active = ["scalp"]

        # De-dup while preserving order.
        seen = set()
        uniq = []
        for p in active:
            if p not in seen:
                uniq.append(p)
                seen.add(p)
        return uniq

    def _sync_regime_playbook_display(self, now_et: Optional[datetime] = None) -> None:
        """Keep regime_data in sync for the dashboard even when the bot is idle
        or the market is closed (not only inside _run_scalp)."""
        when = now_et or datetime.now(ET)
        active = self._choose_active_playbooks(when)
        self._last_active_playbooks = list(active)
        self.regime_data["active_playbooks"] = active
        self.regime_data["playbook_mode"] = "auto" if self.auto_playbooks else "manual"
        # Human-readable combo for any legacy UI still reading `strategy`
        self.regime_data["strategy"] = " + ".join(p.upper() for p in active)

    # ─── Main Loop ────────────────────────────────────────────

    async def run_cycle(self):
        """Run one trading cycle."""
        now_et = datetime.now(ET)
        is_weekend = now_et.weekday() >= 5
        market_time = now_et.time()
        today = now_et.date()

        if self._trading_date != today:
            self._reset_daily(today)
            self._compliance.sweep_settlements()

        # Auto start/stop
        if not is_weekend:
            if market_time >= time(9, 25) and market_time < time(16, 0):
                if not self.active:
                    from app.services.notification_service import notification_service
                    self.active = True
                    self.active_strategy = "scalp"
                    self._log("info", "[Auto-Start] Market opening — Scalp bot ACTIVE")
                    notification_service.send_alert(
                        "🚀 Scalp bot started",
                        f"Today's target: +{self._preset.daily_target_percent}% "
                        f"(${self._day_start_equity * self._preset.daily_target_percent / 100:,.0f})",
                        "SUCCESS",
                    )

            if market_time >= time(16, 0) and self.active:
                from app.services.notification_service import notification_service
                self.active = False
                self._log(
                    "info",
                    f"[Auto-Stop] Market closed | Today P&L: ${self._daily_pnl:+,.2f} "
                    f"({self._daily_trades} trades)",
                )
                notification_service.send_alert(
                    "📊 Today's summary",
                    f"P&L: ${self._daily_pnl:+,.2f} | Trades: {self._daily_trades}",
                    "SUCCESS" if self._daily_pnl >= 0 else "CRITICAL",
                )

        # Dashboard playbook line updates every scan, even when bot is off / market closed.
        self._sync_regime_playbook_display(now_et)

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

        # Quantitative regime (cheap, every 10 scans) + AI regime (every 30)
        if self._scan_count % 10 == 1:
            self._quant_regime_check()
        if self._scan_count % 30 == 1:
            await self._ai_regime_check()

        # ─── One-time cleanup of legacy positions ─────────────
        if not self._v3_cleanup_done:
            await self._cleanup_legacy_positions()
            
            # Wait until all cleanup orders are fulfilled before proceeding to main scalp
            pending = self._alpaca.get_orders(status="open")
            if not pending:
                self._v3_cleanup_done = True
                self._log("info", "✅ Legacy cleanup confirmed — ready for $3,000 scalping!")
            else:
                if self._scan_count % 5 == 1:
                    self._log("info", f"🧹 Waiting for {len(pending)} cleanup orders to fill...")
                return # Keep waiting

        # ─── Execute Strategy ─────────────────────────────────
        try:
            account   = self._alpaca.get_account()
            positions = self._alpaca.get_positions()
            pending   = self._alpaca.get_orders(status="open")
            
            equity    = account["equity"]
            cash      = account["cash"]
            
            pending_symbols = [o["symbol"] for o in pending]

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
            if daily_pnl_pct <= -self._preset.daily_loss_limit_percent:
                self._daily_loss_limit_hit = True
                from app.services.notification_service import notification_service
                self._log("info", f"⛔ DAILY LOSS LIMIT: {daily_pnl_pct:.2f}% — stopping trades for today")
                notification_service.send_alert(
                    "⛔ Daily loss limit hit",
                    f"P&L: ${self._daily_pnl:+,.2f} ({daily_pnl_pct:+.2f}%)\nNo more trades today.",
                    "CRITICAL"
                )
                return

            # Check daily target
            if daily_pnl_pct >= self._preset.daily_target_percent and not self._daily_target_reached:
                self._daily_target_reached = True
                from app.services.notification_service import notification_service
                self._log("info", f"🎯 DAILY TARGET REACHED: +{daily_pnl_pct:.2f}% — reducing aggressiveness")
                notification_service.send_alert(
                    "🎯 Daily target reached",
                    f"P&L: ${self._daily_pnl:+,.2f} (+{daily_pnl_pct:.2f}%)\nReducing aggressiveness to protect gains.",
                    "SUCCESS"
                )

            # Blackout window / VIX halt check (entries only)
            preset = self._preset
            blackout, reason = is_blackout(now_et, preset.blackout_window_minutes)
            score = float(self.regime_data.get("market_score", 50.0))
            vix_level = float(self.regime_data.get("vix_proxy_level", 0.0) or 0.0)
            halt_score = is_halted_score(score)
            halt_vix = vix_level and vix_level >= preset.vix_halt_level

            self.regime_data["blackout"] = bool(blackout or halt_score or halt_vix)
            self.regime_data["blackout_reason"] = (
                reason
                or ("market-score halt" if halt_score else "")
                or (f"VIX {vix_level:.1f} ≥ {preset.vix_halt_level}" if halt_vix else "")
            )

            if self._compliance.is_cooling_down():
                if self._scan_count % 5 == 1:
                    self._log(
                        "info",
                        f"⏸ Loss-streak cooldown {self._compliance.cooldown_remaining_s()}s remaining",
                    )

            await self._run_scalp(account, positions, pending)

        except Exception as e:
            self._log("error", f"Cycle error: {str(e)}")
            logger.error(f"Trading cycle error: {e}")

    # ── Legacy Position Cleanup ─────────────────────────────────

    async def _cleanup_legacy_positions(self):
        """Sell ALL existing positions from old strategy. V3 starts with a clean slate."""
        try:
            positions = self._alpaca.get_positions()
            if not positions:
                self._log("info", "✅ No legacy positions — clean start!")
                return

            self._log("info", f"🧹 Cleaning up {len(positions)} legacy positions from old strategy...")

            for pos in positions:
                symbol = pos["symbol"]
                raw_qty = int(pos["qty"])
                
                if raw_qty == 0:
                    continue
                
                if raw_qty > 0:
                    self._log("info", f"  Selling {raw_qty}x {symbol} (legacy cleanup)")
                    res = self._alpaca.submit_market_order(symbol, raw_qty, "sell")
                else:
                    # Negative qty (short): cover with a buy
                    cover_qty = abs(raw_qty)
                    self._log("info", f"  Covering {cover_qty}x {symbol} short position (legacy cleanup)")
                    res = self._alpaca.submit_market_order(symbol, cover_qty, "buy")

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
        self._trading_date = today
        self._daily_pnl = 0.0
        self._daily_trades = 0
        self._daily_target_reached = False
        self._daily_loss_limit_hit = False
        self._position_peaks.clear()

        # Get current equity as day start
        try:
            account = self._alpaca.get_account()
            self._day_start_equity = account["equity"]
        except Exception:
            self._day_start_equity = settings.initial_capital

        self._log("info", f"📅 New trading day: {today} | Start equity: ${self._day_start_equity:,.2f}")
        self._log(
            "info",
            f"🎯 Today's target: +${self._day_start_equity * self._preset.daily_target_percent / 100:,.2f} "
            f"(+{self._preset.daily_target_percent}%)",
        )

    # ─── GFV Prevention (delegates to self._compliance) ─────

    def _get_settled_cash(self, total_cash: float) -> float:
        return self._compliance.settled_cash(total_cash)

    def _can_sell(self, symbol: str) -> bool:
        if not self._compliance.can_sell(symbol):
            self._log(
                "info",
                f"⚠️ GFV prevention: holding {symbol} (bought with unsettled cash)",
            )
            return False
        return True

    # ─── Regime checks ────────────────────────────────────────

    def _apply_preset_from_score(self, score: float, source: str):
        """Deterministic score → preset mapping. Logs only when it changes."""
        new_preset = preset_for_score(score)
        if new_preset.level != self._preset.level:
            self._log(
                "info",
                f"🎚️ Risk auto-adjust ({source}): {self._preset.level} → {new_preset.level} "
                f"(score={score:.1f})",
            )
            self._preset = new_preset
        self.regime_data.update(
            {
                "risk_level": self._preset.level,
                "market_score": round(score, 1),
                "market_level": market_level_for_score(score),
                "max_position_percent": self._preset.max_position_percent,
                "stop_loss_percent": self._preset.stop_loss_percent,
                "take_profit_percent": self._preset.take_profit_percent,
                "daily_target": f"+{self._preset.daily_target_percent}%",
            }
        )

    def _quant_regime_check(self):
        """Cheap quantitative regime using ETF proxies (no LLM)."""
        try:
            quant = self._regime.compute_scores()
            score = quant["composite"]
            tilt = quant.get("sector_tilt")
            self.regime_data.update(
                {
                    "quant_scores": quant["scores"],
                    "quant_changes_5d_pct": quant["changes_5d_pct"],
                    "vix_proxy_level": quant["vix_proxy_level"],
                    "sector_tilt": tilt,
                    "timestamp": datetime.now().strftime("%b %d, %Y, %-I:%M%p"),
                }
            )
            if tilt:
                self.focus_symbols = self._regime.suggested_universe(tilt)[: self._preset.universe_size]
                self.regime_data["focus_symbols"] = self.focus_symbols
            self._apply_preset_from_score(score, source="quant")
        except Exception as exc:  # noqa: BLE001
            logger.warning("quant regime check failed: %s", exc)

    async def _ai_regime_check(self):
        """Use AI to analyze news and adjust focus symbols."""
        try:
            from app.services.analysis_agent import analysis_agent
            news = self._alpaca.get_latest_news(
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

                # Combine AI market_score with quantitative score (60/40)
                ai_score = float(regime.get("market_score", 50.0))
                quant_score = float(self.regime_data.get("market_score", 50.0))
                blended = 0.6 * quant_score + 0.4 * ai_score

                self.regime_data.update(
                    {
                        "reasoning": regime.get("reasoning", ""),
                        "prev_strategy": old_strat,
                        "prev_risk_level": old_risk,
                        "ai_market_score": round(ai_score, 1),
                        "market_scores": regime.get("market_scores", {}),
                        "daily_pnl": self.regime_data.get("daily_pnl", "$0.00"),
                        "account_type": settings.account_type,
                        "timestamp": datetime.now().strftime("%b %d, %Y, %-I:%M%p"),
                    }
                )
                self._apply_preset_from_score(blended, source="ai+quant")

                if old_risk != self._preset.level:
                    from app.services.notification_service import notification_service
                    notification_service.send_alert(
                        "🔄 Market Regime Update",
                        f"Risk: {old_risk} → {self._preset.level}\nReason: {regime.get('reasoning', '')}",
                        "INFO",
                    )

        except Exception as e:
            logger.warning(f"AI regime check failed: {e}")

    # ─── Scalping Strategy ────────────────────────────────────

    async def _run_scalp(self, account: dict, positions: list, pending: list):
        """
        Cash-account scalping with:
        - High-water-mark trailing stop per position
        - Marketable-limit orders + spread filter
        - GFV tracking via self._compliance
        - Daily trade cap + loss-streak cooldown
        - Event / opening-auction / VIX blackout for entries only
        """
        preset = self._preset
        equity  = account["equity"]
        cash    = account["cash"]
        settled = self._compliance.settled_cash(cash)
        now_et = datetime.now(ET)
        self._sync_regime_playbook_display(now_et)
        active_playbooks = list(self.regime_data.get("active_playbooks") or self._last_active_playbooks)

        pending_symbols = [o["symbol"] for o in pending]
        current_symbols = [p["symbol"] for p in positions]

        # ── 1. Manage open positions ────────────────────────────
        for pos in positions:
            symbol = pos["symbol"]
            plpc   = pos["unrealized_plpc"]
            pl_usd = pos["unrealized_pl"]
            qty_to_sell = int(pos["qty"])

            if qty_to_sell < 0:
                if symbol in pending_symbols:
                    continue
                self._log("error", f"⚠️ EMERGENCY COVER {symbol}: qty={pos['qty']}")
                self._alpaca.submit_market_order(symbol, abs(qty_to_sell), "buy")
                continue
            if qty_to_sell <= 0:
                continue
            if not self._can_sell(symbol):
                continue

            # Maintain peak for trailing stop
            peak = self._position_peaks.get(symbol, plpc)
            if plpc > peak:
                peak = plpc
                self._position_peaks[symbol] = peak

            snapshot = self._alpaca.get_snapshot(symbol) or {}
            exit_reason = None

            if plpc <= -(preset.stop_loss_percent / 100):
                exit_reason = f"🔴 STOP {plpc*100:+.2f}%"
            elif plpc >= (preset.take_profit_percent / 100):
                exit_reason = f"🟢 TP {plpc*100:+.2f}%"
            elif peak > 0 and (peak - plpc) >= (preset.trailing_trigger_percent / 100) and plpc > 0:
                exit_reason = f"🟡 TRAIL peak={peak*100:+.2f}% now={plpc*100:+.2f}%"

            if not exit_reason:
                continue

            self._log("sell", f"{exit_reason} {symbol} (${pl_usd:+,.2f})")
            res = self._executor.sell(symbol, qty_to_sell, snapshot, preset.spread_filter_percent)
            if "error" in res:
                self._log("error", f"Exit failed {symbol}: {res['error']}")
                continue

            exit_price = float(pos.get("current_price") or pos.get("avg_entry_price") or 0.0)
            cost_basis = qty_to_sell * float(pos.get("avg_entry_price") or 0.0)
            self._compliance.record_sell(symbol, qty_to_sell, exit_price, cost_basis)
            self._position_peaks.pop(symbol, None)

            self._daily_trades += 1
            self.session_stats["total_trades"] += 1
            if pl_usd > 0:
                self.session_stats["winning_trades"] += 1
                self.session_stats["win_sum"]        += pl_usd
            else:
                self.session_stats["losing_trades"]  += 1
                self.session_stats["loss_sum"]       += abs(pl_usd)
            self.session_stats["total_pnl"] += pl_usd

        # Loss-streak circuit breaker
        if self._compliance.loss_streak >= 3 and not self._compliance.is_cooling_down():
            self._compliance.register_loss_streak_cooldown(minutes=15)
            self._log("info", "⏸ 3 consecutive losses → 15-minute cooldown")

        # ── 2. Entry gating ─────────────────────────────────────
        if self.regime_data.get("blackout"):
            if self._scan_count % 5 == 1:
                self._log(
                    "info",
                    f"🚫 No new entries — {self.regime_data.get('blackout_reason','blackout')}",
                )
            return
        if self._compliance.is_cooling_down():
            return
        if self._daily_trades >= preset.max_trades_per_day:
            if self._scan_count % 10 == 1:
                self._log("info", f"🧯 Daily trade cap {preset.max_trades_per_day} reached")
            return

        pending_buys = [o["symbol"] for o in pending if o["side"] == "buy"]
        slots = preset.max_concurrent_positions - (len(current_symbols) + len(set(pending_buys)))
        if slots <= 0:
            return
        if settled < 100:
            self._log("info", f"💤 Settled cash too low: ${settled:,.2f}")
            return

        entry_threshold = preset.entry_score_threshold
        if self._daily_target_reached:
            entry_threshold = max(entry_threshold, 70)

        # ── 3. Scan universe ────────────────────────────────────
        scored = []
        for symbol in self.focus_symbols[: preset.universe_size]:
            if symbol in current_symbols:
                continue
            block = self._compliance.can_enter(symbol)
            if block:
                continue
            # Earnings-today skip (earnings dates can be injected later)
            if symbol_is_earnings_today(symbol, getattr(self, "_earnings_today", {})):
                continue

            try:
                bars = self._alpaca.get_bars(symbol, "5Min", 50)
                if len(bars) < 20:
                    bars = self._alpaca.get_bars(symbol, "1Day", 30)
                    if len(bars) < 14:
                        continue

                closes  = [b["close"] for b in bars]
                volumes = [b.get("volume", 0) for b in bars]
                indicators = self._calculate_indicators(closes)
                price = closes[-1]

                total, reasons = combine_playbooks(
                    price=price,
                    indicators=indicators,
                    bars=bars,
                    volumes=volumes,
                    now=now_et,
                    news_score=self.regime_data.get("news_score", 0.0) or 0.0,
                    enabled=active_playbooks,
                )

                if len(closes) >= 10:
                    ma10 = sum(closes[-10:]) / 10
                    if price > ma10:
                        total += 10
                        reasons.append("P>MA10")

                if total >= entry_threshold:
                    scored.append((total, symbol, price, reasons))

            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Scan error for {symbol}: {exc}")

        # ── 4. Execute ──────────────────────────────────────────
        scored.sort(key=lambda x: -x[0])
        for score, symbol, price, reasons in scored[:slots]:
            if symbol in pending_symbols:
                continue

            max_value = equity * (preset.max_position_percent / 100)
            buy_power = min(max_value, settled * 0.95)
            qty = int(buy_power / price)
            if qty <= 0:
                continue

            snapshot = self._alpaca.get_snapshot(symbol) or {}
            bid, ask, spread = spread_info(snapshot)
            if spread > preset.spread_filter_percent:
                self._log(
                    "info",
                    f"⏭ Skip {symbol}: spread {spread:.3f}% > {preset.spread_filter_percent:.3f}%",
                )
                continue

            cost = qty * price
            self._log(
                "signal",
                f"📊 BUY {symbol}: score={score} | {' + '.join(reasons)} | "
                f"${price:.2f} × {qty} = ${cost:,.0f}",
            )

            settled_before = settled
            res = self._executor.buy(symbol, qty, snapshot, preset.spread_filter_percent)
            if "error" in res:
                self._log("error", f"Order failed {symbol}: {res['error']}")
                continue

            self._compliance.record_buy(symbol, qty, price, settled_before)
            self._position_peaks[symbol] = 0.0
            self._log("buy", f"✅ BOUGHT {qty} × {symbol} @ ~${price:.2f} (${cost:,.0f})")
            self._daily_trades += 1
            self.session_stats["total_trades"] += 1
            settled -= cost

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
            "preset": self._preset.level,
            "compliance": self._compliance.status(),
        }


