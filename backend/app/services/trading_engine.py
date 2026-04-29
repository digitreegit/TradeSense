"""
TradeSense - Trading Engine v4
Cash-account scalping with compliance, event, and regime guards.

v4.1 adds:
- Capital-scale aware risk presets (3k vs 30k) via core.risk_presets
- WebSocket-first snapshot reads (AlpacaService already prefers streaming)
- Marketable-limit + IOC TIF through a single Executor abstraction
- Execution-quality logging (signal → order → fill → slippage JSONL)

Delegates:
- Compliance (GFV / free-riding / wash-sale / cooldowns) → self._compliance
- Macro regime score + universe tilt                    → regime_service
- Macro event / opening-auction blackout                → event_calendar
- Risk preset tables driven by regime score             → core.risk_presets
- Entry scoring (scalp + VWAP + ORB + EOD + news-fade)  → playbooks
- Marketable-limit orders + spread filter               → execution_service
- Per-order slippage + latency JSONL                    → execution_logger
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional

import pytz

from app.core.config import initial_capital_for_scale, resolved_capital_scale, settings
from app.core.risk_presets import (
    RISK_PRESETS_FOR,
    is_halted_score,
    market_level_for_score,
    preset_for_level,
    preset_for_score,
)
from app.services.alpaca_service import AlpacaService
from app.services.compliance_service import ComplianceService
from app.services.event_calendar import is_blackout, symbol_is_earnings_today
from app.services.execution_logger import ExecutionLogger
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
    market_open = time(9, 30)
    market_close = time(16, 0)
    return market_open <= now_et.time() <= market_close


def is_extended_equity_session(now_et: datetime) -> bool:
    """Pre 04:00–09:30 ET or post 16:00–20:00 ET (weekdays)."""
    if now_et.weekday() >= 5:
        return False
    t = now_et.time()
    pre = time(4, 0) <= t < time(9, 30)
    post = time(16, 0) < t <= time(20, 0)
    return pre or post


def is_tradable_equity_session(now_et: datetime, *, allow_extended: bool) -> bool:
    """RTH or (optional) Alpaca stock extended hours."""
    if is_market_open():
        return True
    return bool(allow_extended and is_extended_equity_session(now_et))


def _norm_broker_status(raw: Optional[str]) -> str:
    if not raw:
        return ""
    s = str(raw).lower()
    if "." in s:
        s = s.split(".")[-1]
    return s.strip()


class TradingEngine:
    """Cash-account scalp engine with GFV prevention."""

    SCALP_UNIVERSE = [
        "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AMD", "TSLA",
        "SPY", "QQQ", "INTC", "NFLX", "AVGO", "CRM", "UBER",
        # Added for the $30k scale — higher-ADV liquid names with tight spreads
        "MU", "COIN", "PLTR", "SMCI", "IWM", "DIA", "XLK", "XLE",
    ]

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

    def __init__(
        self,
        alpaca: AlpacaService,
        compliance: ComplianceService,
        owner_email: Optional[str] = None,
        log_dir: Optional[Path] = None,
        owner_user_id: Optional[int] = None,
    ):
        self._alpaca = alpaca
        self._compliance = compliance
        self._owner_user_id = owner_user_id
        self._notify_user_id: Optional[int] = owner_user_id
        self._scale = resolved_capital_scale()
        self._initial_capital = initial_capital_for_scale(self._scale)
        if self._alpaca.paper_trading:
            self._alpaca.initial_capital_override = self._initial_capital
        else:
            self._alpaca.initial_capital_override = None

        self._exec_logger = ExecutionLogger(
            log_dir=log_dir,
            owner_tag=(owner_email or "default"),
        )
        self._executor = Executor(alpaca, exec_logger=self._exec_logger)
        self._regime = RegimeService(alpaca)
        self.owner_email = (owner_email or "").strip().lower() or None

        self.active = False
        self.active_strategy: Optional[str] = None
        self.last_regime_reason: str = ""

        # Focus universe (AI + regime tilt can override)
        universe_slice = 12 if self._scale == "30k" else 8
        self.focus_symbols: list = list(self.SCALP_UNIVERSE[:universe_slice])
        self.focus_sectors: list = ["tech_ai", "tech_software"]

        # Daily tracking
        self._trading_date: Optional[date] = None
        self._daily_pnl: float = 0.0
        self._daily_trades: int = 0
        self._daily_target_reached: bool = False
        self._daily_loss_limit_hit: bool = False
        self._day_start_equity: float = self._initial_capital

        # Per-position peaks for trailing stop high-water mark
        self._position_peaks: dict = {}

        # Active risk preset (respects scale)
        table = RISK_PRESETS_FOR(self._scale)
        self._preset = table["moderate"]

        # broker_id → metadata for compliance + stats after terminal status
        self._pending_reconcile: dict = {}

        self.regime_data: dict = {
            "strategy": "scalp",
            "reasoning": (
                f"{self._scale}-scale scalp — "
                f"${self._initial_capital:,.0f} → "
                f"+{self._preset.daily_target_percent}%/day"
            ),
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
            "capital_scale": self._scale,
            "blackout": False,
            "blackout_reason": "",
            "equity_session": "closed",
            "allow_extended_hours": getattr(settings, "allow_extended_hours", False),
            "timestamp": datetime.now().strftime("%b %d, %Y, %-I:%M%p"),
        }

        # Session stats
        self.trade_logs: list = []
        self.session_stats = {
            "total_trades":   0,
            "winning_trades": 0,
            "losing_trades":  0,
            "win_sum":        0.0,
            "loss_sum":       0.0,
            "total_pnl":      0.0,
            "max_drawdown":   0.0,
            "slippage_bps_sum": 0.0,
            "slippage_bps_count": 0,
        }
        self._scan_count = 0
        self._v3_cleanup_done = False

        # Playbook routing
        self.auto_playbooks: bool = True
        self.manual_playbooks: list = ["scalp", "vwap", "orb", "eod"]
        self._last_active_playbooks: list = list(self.manual_playbooks)
        self._sync_regime_playbook_display()

    def _entry_order_tif(self) -> str:
        raw = (getattr(settings, "default_order_tif", "") or "").strip().lower()
        if raw in ("day", "ioc", "fok", "gtc"):
            return raw
        return (self._preset.default_tif or "ioc").strip().lower()

    def _exit_order_tif(self) -> str:
        raw = (getattr(settings, "exit_order_tif", "") or "").strip().lower()
        if raw in ("day", "ioc", "fok", "gtc"):
            return raw
        return "day"

    def _exit_tif_for_reason(self, exit_reason: str) -> str:
        """Stop / loss → IOC (cut rest); TP / trail → DAY (better partials)."""
        er = (exit_reason or "").upper()
        if "STOP" in er or "🔴" in (exit_reason or ""):
            raw = (getattr(settings, "exit_stop_loss_tif", "ioc") or "ioc").strip().lower()
        else:
            tp = (getattr(settings, "exit_take_profit_tif", "") or "").strip().lower()
            raw = tp if tp in ("day", "ioc", "fok", "gtc") else self._exit_order_tif()
        if raw in ("day", "ioc", "fok", "gtc"):
            return raw
        return "ioc"

    def _use_extended_limit_orders(self, now_et: datetime) -> bool:
        """Alpaca extended session requires limit + DAY + extended_hours flag."""
        return bool(
            getattr(settings, "allow_extended_hours", False)
            and is_extended_equity_session(now_et)
            and not is_market_open()
        )

    def set_owner_email(self, email: Optional[str]) -> None:
        """Attach/update recipient email for per-user notifications."""
        self.owner_email = (email or "").strip().lower() or None

    # ─── Capital scale (hot-swap 3k/10k/30k preset tables) ─────

    def get_scale_info(self) -> dict:
        """Report current scale + preset level so the UI can render the selector."""
        return {
            "scale": self._scale,
            "level": self._preset.level,
            "auto": True,
            "available": ["3k", "10k", "30k"],
            "preset": self._preset.as_dict(),
            "paper_trading": self._alpaca.paper_trading,
            "initial_capital": self._initial_capital,
        }

    def set_capital_scale(self, scale: str) -> dict:
        """Switch the active preset table at runtime.

        Keeps the current risk *level* (conservative/moderate/aggressive)
        and swaps only the scale-dependent parameters. Safe to call while
        the bot is active — the change is visible on the next scan.
        """
        new_scale = (scale or "").strip().lower()
        if new_scale not in ("3k", "10k", "30k"):
            raise ValueError(f"unknown capital scale: {scale!r}")
        if new_scale == self._scale:
            return {**self.get_scale_info(), "paper_trading": self._alpaca.paper_trading}

        old_scale = self._scale
        self._scale = new_scale
        self._initial_capital = initial_capital_for_scale(new_scale)
        if self._alpaca.paper_trading:
            self._alpaca.initial_capital_override = self._initial_capital
            self._alpaca.reset_paper_virtual_baseline()

        self._preset = preset_for_level(self._preset.level, scale=new_scale)

        self.regime_data.update(
            {
                "capital_scale": self._scale,
                "risk_level": self._preset.level,
                "max_position_percent": self._preset.max_position_percent,
                "stop_loss_percent": self._preset.stop_loss_percent,
                "take_profit_percent": self._preset.take_profit_percent,
                "daily_target": f"+{self._preset.daily_target_percent}%",
                "timestamp": datetime.now().strftime("%b %d, %Y, %-I:%M%p"),
            }
        )
        self._log(
            "info",
            f"🔧 Capital scale switched: {old_scale} → {new_scale} | "
            f"preset={self._preset.level.upper()} | TIF={self._preset.default_tif.upper()} | "
            f"slots={self._preset.max_concurrent_positions} | "
            f"trades/day={self._preset.max_trades_per_day}",
        )
        return self.get_scale_info()

    def set_paper_trading(self, paper: bool) -> dict:
        """Switch Alpaca paper vs live endpoint (requires stored API keys)."""
        from app.db import users_db
        from app.services.user_runtime import load_alpaca_keys_for_user

        if self._owner_user_id is None:
            raise ValueError("paper/live mode can only be changed for signed-in users with saved keys")
        uid = self._owner_user_id
        row = users_db.get_user_by_id(uid)
        if not row or not (row.get("alpaca_key_enc") and row.get("alpaca_secret_enc")):
            raise ValueError("save Alpaca API keys before switching paper or live mode")

        want = bool(paper)
        if want == self._alpaca.paper_trading:
            return {**self.get_scale_info(), "paper_trading": want}

        self._alpaca.set_paper_trading(want)
        k, s = load_alpaca_keys_for_user(uid)
        ok = self._alpaca.initialize_with_keys(k, s, paper_trading=want)
        if not ok:
            self._alpaca.set_paper_trading(not want)
            self._alpaca.initialize_with_keys(k, s, paper_trading=not want)
            raise ValueError("could not connect with the selected mode; check that your keys match paper or live")

        users_db.set_alpaca_paper_trading(uid, want)
        if want:
            self._alpaca.initial_capital_override = self._initial_capital
        else:
            self._alpaca.initial_capital_override = None
        if want:
            self._alpaca.reset_paper_virtual_baseline()

        mode = "paper" if want else "live"
        self._log("info", f"🔀 Alpaca mode: {mode.upper()} trading API")
        return {**self.get_scale_info(), "paper_trading": want}

    # ─── Control ──────────────────────────────────────────────

    def start(
        self,
        strategy: str = "scalp",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        max_position: Optional[float] = None,
        risk_level: Optional[str] = None,
    ):
        self.active = True
        self.active_strategy = strategy
        self.regime_data["timestamp"] = datetime.now().strftime("%b %d, %Y, %-I:%M%p")
        self._sync_regime_playbook_display()

        if risk_level:
            self._preset = preset_for_level(risk_level, scale=self._scale)

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
            f"🚀 Bot started [{self._scale}] — {preset.level.upper()} | "
            f"Capital: ${self._initial_capital:,.0f} | TIF: {preset.default_tif.upper()}",
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
        logger.info(
            "Trading engine started: %s (scale=%s preset=%s)",
            strategy, self._scale, preset.level,
        )

    def stop(self):
        self.active = False
        self._log("info", "Trading engine stopped")
        logger.info("Trading engine stopped")

    @property
    def is_active(self) -> bool:
        return self.active

    # ─── Playbook configuration ───────────────────────────────

    def get_playbook_config(self) -> dict:
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
        if not self.auto_playbooks:
            return list(self.manual_playbooks)

        t = now_et.time()
        score = float(self.regime_data.get("market_score", 50.0) or 50.0)
        news = float(self.regime_data.get("news_score", 0.0) or 0.0)

        active: list = []
        if time(9, 35) <= t < time(11, 0):
            active.append("orb")
        if time(10, 0) <= t < time(15, 30):
            active.append("vwap")
        if time(9, 35) <= t < time(15, 45):
            active.append("scalp")
        if time(15, 30) <= t < time(15, 58):
            active.append("eod")
        if news <= -0.6:
            active.append("news-fade")
        if score < 25:
            active = [p for p in active if p in ("news-fade",)] or ["news-fade"]
        if not active:
            active = ["scalp"]

        seen = set()
        uniq = []
        for p in active:
            if p not in seen:
                uniq.append(p)
                seen.add(p)
        return uniq

    def _sync_regime_playbook_display(self, now_et: Optional[datetime] = None) -> None:
        when = now_et or datetime.now(ET)
        active = self._choose_active_playbooks(when)
        self._last_active_playbooks = list(active)
        self.regime_data["active_playbooks"] = active
        self.regime_data["playbook_mode"] = "auto" if self.auto_playbooks else "manual"
        self.regime_data["strategy"] = " + ".join(p.upper() for p in active)

    # ─── Main Loop ────────────────────────────────────────────

    async def run_cycle(self):
        now_et = datetime.now(ET)
        is_weekend = now_et.weekday() >= 5
        market_time = now_et.time()
        today = now_et.date()

        if self._trading_date != today:
            self._reset_daily(today)
            self._compliance.sweep_settlements()

        ext_schedule = getattr(settings, "allow_extended_hours", False)
        sess_start = time(3, 55) if ext_schedule else time(9, 20)
        sess_end = time(20, 5) if ext_schedule else time(16, 10)

        if not is_weekend:
            if market_time >= sess_start and market_time < sess_end:
                if not self.active:
                    from app.services.notification_service import notification_service
                    self.active = True
                    self.active_strategy = "scalp"
                    label = "Extended + RTH" if ext_schedule else "RTH"
                    self._log("info", f"[Auto-Start] {label} window — Scalp bot ACTIVE")
                    notification_service.send_alert(
                        "🚀 Scalp bot started",
                        f"Today's target: +{self._preset.daily_target_percent}% "
                        f"(${self._day_start_equity * self._preset.daily_target_percent / 100:,.0f})",
                        "SUCCESS",
                        to_email=self.owner_email,
                        user_id=self._notify_user_id,
                    )

            if market_time >= sess_end and self.active:
                from app.services.notification_service import notification_service
                self.active = False
                self._log(
                    "info",
                    f"[Auto-Stop] Market closed | Today P&L: ${self._daily_pnl:+,.2f} "
                    f"({self._daily_trades} trades)",
                )
                try:
                    account = self._alpaca.get_account()
                    notification_service.send_daily_summary(
                        to_email=self.owner_email or "",
                        trading_date=today.isoformat(),
                        daily_pnl=float(self._daily_pnl),
                        daily_pnl_pct=((self._daily_pnl / self._day_start_equity) * 100.0)
                        if self._day_start_equity > 0
                        else 0.0,
                        equity=float(account.get("equity", 0.0)),
                        portfolio_value=float(account.get("portfolio_value", account.get("equity", 0.0))),
                        cash=float(account.get("cash", 0.0)),
                        trades=int(self._daily_trades),
                        win_rate_pct=float(self.get_stats().get("win_rate", 0.0)),
                        user_id=self._notify_user_id,
                    )
                except Exception as exc:
                    logger.warning("Failed to send daily summary email: %s", exc)

        self._sync_regime_playbook_display(now_et)

        if is_market_open():
            self.regime_data["equity_session"] = "rth"
        elif is_extended_equity_session(now_et):
            self.regime_data["equity_session"] = "extended"
        else:
            self.regime_data["equity_session"] = "closed"
        self.regime_data["allow_extended_hours"] = getattr(settings, "allow_extended_hours", False)

        if not self.active:
            return

        self._scan_count += 1

        allow_ext = getattr(settings, "allow_extended_hours", False)
        if not is_tradable_equity_session(now_et, allow_extended=allow_ext):
            if self._scan_count % 5 == 1:
                self._log(
                    "info",
                    "Standby — outside equity session "
                    f"(RTH 9:30–4:00 ET"
                    f"{'; extended 4:00–9:30 & 4–8p enabled' if allow_ext else ''}) "
                    f"| Now: {now_et.strftime('%H:%M ET')}",
                )
            return

        if self._daily_loss_limit_hit:
            if self._scan_count % 10 == 1:
                self._log("info", f"⛔ Daily loss limit hit (${self._daily_pnl:+,.2f}). No more trades today.")
            return

        # Regime checks
        if self._scan_count % 10 == 1:
            self._quant_regime_check()
        if self._scan_count % 30 == 1:
            await self._ai_regime_check()

        # Reconcile any outstanding order fills (for slippage logging)
        self._reconcile_pending_fills()

        # One-time cleanup of legacy positions
        if not self._v3_cleanup_done:
            await self._cleanup_legacy_positions()
            pending = self._alpaca.get_orders(status="open")
            cleanup_pending = [o for o in pending if str(o.get("side", "")).lower() == "sell"]
            if not pending:
                self._v3_cleanup_done = True
                self._log("info", "✅ Legacy cleanup confirmed — ready for scalping!")
            else:
                if self._scan_count % 5 == 1:
                    self._log(
                        "info",
                        f"🧹 Waiting for {len(cleanup_pending)} cleanup orders to fill "
                        f"(open total: {len(pending)})...",
                    )
                if cleanup_pending:
                    return

        try:
            account = self._alpaca.get_account()
            positions = self._alpaca.get_positions()
            pending = self._alpaca.get_orders(status="open")
            equity = account["equity"]
            cash = account["cash"]

            self._daily_pnl = equity - self._day_start_equity
            daily_pnl_pct = (self._daily_pnl / self._day_start_equity) * 100

            self.regime_data["daily_pnl"] = f"${self._daily_pnl:+,.2f} ({daily_pnl_pct:+.2f}%)"

            self._log(
                "info",
                f"Scan #{self._scan_count} | Equity: ${equity:,.2f} | "
                f"Daily P&L: ${self._daily_pnl:+,.2f} ({daily_pnl_pct:+.2f}%) | "
                f"Positions: {len(positions)} | Trades: {self._daily_trades}",
            )

            if daily_pnl_pct <= -self._preset.daily_loss_limit_percent:
                self._daily_loss_limit_hit = True
                from app.services.notification_service import notification_service
                self._log("info", f"⛔ DAILY LOSS LIMIT: {daily_pnl_pct:.2f}% — stopping trades for today")
                notification_service.send_alert(
                    "⛔ Daily loss limit hit",
                    f"P&L: ${self._daily_pnl:+,.2f} ({daily_pnl_pct:+.2f}%)\nNo more trades today.",
                    "CRITICAL",
                    to_email=self.owner_email,
                    user_id=self._notify_user_id,
                )
                return

            if daily_pnl_pct >= self._preset.daily_target_percent and not self._daily_target_reached:
                self._daily_target_reached = True
                from app.services.notification_service import notification_service
                self._log("info", f"🎯 DAILY TARGET REACHED: +{daily_pnl_pct:.2f}% — reducing aggressiveness")
                notification_service.send_alert(
                    "🎯 Daily target reached",
                    f"P&L: ${self._daily_pnl:+,.2f} (+{daily_pnl_pct:.2f}%)\nReducing aggressiveness to protect gains.",
                    "SUCCESS",
                    to_email=self.owner_email,
                    user_id=self._notify_user_id,
                )

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

    # ─── Fill reconciliation for execution quality logging ─────────

    def _reconcile_pending_fills(self) -> None:
        """Poll broker for terminal order status; log fills + apply compliance on *filled* qty."""
        if not self._pending_reconcile:
            return
        to_drop: list = []
        for broker_id, meta in list(self._pending_reconcile.items()):
            try:
                info = self._alpaca.get_order(broker_id)
            except Exception:
                continue
            if not info:
                continue
            st = _norm_broker_status(info.get("status"))
            if st == "partially_filled":
                continue
            pending_live = {
                "new", "pending_new", "accepted", "pending_replace",
                "pending_cancel", "calculated", "held", "suspended",
            }
            if st in pending_live:
                continue
            terminal = {"filled", "canceled", "expired", "rejected", "done_for_day"}
            if st not in terminal:
                continue

            client_id = meta["client_id"]
            filled_price = float(info.get("filled_avg_price") or 0.0)
            filled_qty = float(info.get("filled_qty") or 0.0)
            slip = self._exec_logger.log_fill(
                client_id,
                filled_avg_price=filled_price,
                filled_qty=filled_qty,
                status=st,
                filled_at=info.get("filled_at"),
            )
            if slip is not None:
                self.session_stats["slippage_bps_sum"] += slip
                self.session_stats["slippage_bps_count"] += 1

            sym = meta["symbol"]
            if meta["kind"] == "buy" and filled_qty > 0:
                px = filled_price or float(meta.get("signal_price") or 0.0)
                self._compliance.record_buy(
                    sym, int(filled_qty), px, float(meta.get("settled_before") or 0.0)
                )
                self._position_peaks[sym] = 0.0
                self._daily_trades += 1
                self.session_stats["total_trades"] += 1
                self._log("buy", f"✅ Fill BUY {int(filled_qty)} × {sym} @ ${px:.2f}")
            elif meta["kind"] == "sell" and filled_qty > 0:
                px = filled_price or float(meta.get("signal_price") or 0.0)
                avg_e = float(meta.get("avg_entry_price") or 0.0)
                cost_basis = filled_qty * avg_e
                self._compliance.record_sell(sym, int(filled_qty), px, cost_basis)
                intended = max(1, int(meta.get("intended_qty") or 1))
                pl_full = meta.get("exit_pl_usd")
                if pl_full is not None:
                    pl_part = float(pl_full) * (filled_qty / float(intended))
                else:
                    pl_part = 0.0
                if filled_qty + 1e-9 >= intended:
                    self._position_peaks.pop(sym, None)
                else:
                    self._log("info", f"Partial exit {sym}: filled {int(filled_qty)}/{intended}")
                self._daily_trades += 1
                self.session_stats["total_trades"] += 1
                if pl_part > 0:
                    self.session_stats["winning_trades"] += 1
                    self.session_stats["win_sum"] += pl_part
                elif pl_part < 0:
                    self.session_stats["losing_trades"] += 1
                    self.session_stats["loss_sum"] += abs(pl_part)
                self.session_stats["total_pnl"] += pl_part
                self._log("sell", f"✅ Fill SELL {int(filled_qty)} × {sym} @ ${px:.2f}")

            to_drop.append(broker_id)
        for bid in to_drop:
            self._pending_reconcile.pop(bid, None)

    def _track_for_reconcile(
        self,
        order: dict,
        *,
        kind: str,
        symbol: str,
        settled_before: float = 0.0,
        signal_price: float = 0.0,
        avg_entry_price: float = 0.0,
        intended_qty: int = 0,
        exit_pl_usd: Optional[float] = None,
    ) -> None:
        bid = order.get("id")
        cid = order.get("client_id")
        if not bid or not cid:
            return
        self._pending_reconcile[str(bid)] = {
            "client_id": cid,
            "kind": kind,
            "symbol": symbol,
            "settled_before": float(settled_before),
            "signal_price": float(signal_price),
            "avg_entry_price": float(avg_entry_price),
            "intended_qty": int(intended_qty or order.get("qty") or 0),
            "exit_pl_usd": exit_pl_usd,
        }

    # ── Legacy Position Cleanup ─────────────────────────────────

    async def _cleanup_legacy_positions(self):
        try:
            positions = self._alpaca.get_positions()
            if not positions:
                self._log("info", "✅ No legacy positions — clean start!")
                return

            self._log("info", f"🧹 Cleaning up {len(positions)} legacy positions from old strategy...")

            now_l = datetime.now(ET)
            use_ext_l = self._use_extended_limit_orders(now_l)
            acct_l = self._alpaca.get_account()
            settled_l = self._compliance.settled_cash(float(acct_l.get("cash") or 0.0))

            for pos in positions:
                symbol = pos["symbol"]
                raw_qty = int(pos["qty"])
                if raw_qty == 0:
                    continue
                snapshot = self._alpaca.get_snapshot(symbol) or {}
                ref = float(pos.get("current_price") or 0.0)
                wide_spread = 5.0
                xtif = "day" if use_ext_l else self._exit_order_tif()
                etif = "day" if use_ext_l else self._entry_order_tif()
                if raw_qty > 0:
                    self._log("info", f"  Selling {raw_qty}x {symbol} (legacy cleanup)")
                    res = self._executor.sell(
                        symbol,
                        raw_qty,
                        snapshot,
                        wide_spread,
                        tif=xtif,
                        extended_hours=use_ext_l,
                        reasons=["legacy_cleanup"],
                        ref_price=ref,
                    )
                    if "error" not in res:
                        self._track_for_reconcile(
                            res,
                            kind="sell",
                            symbol=symbol,
                            signal_price=ref,
                            avg_entry_price=float(pos.get("avg_entry_price") or ref),
                            intended_qty=raw_qty,
                            exit_pl_usd=None,
                        )
                else:
                    cover_qty = abs(raw_qty)
                    self._log("info", f"  Covering {cover_qty}x {symbol} short position (legacy cleanup)")
                    res = self._executor.buy(
                        symbol,
                        cover_qty,
                        snapshot,
                        wide_spread,
                        tif=etif,
                        extended_hours=use_ext_l,
                        reasons=["legacy_short_cover"],
                        ref_price=ref,
                    )
                    if "error" not in res:
                        self._track_for_reconcile(
                            res,
                            kind="buy",
                            symbol=symbol,
                            settled_before=settled_l,
                            signal_price=ref,
                            intended_qty=cover_qty,
                        )

                if "error" in res:
                    self._log("error", f"  Failed to close {symbol}: {res['error']}")
                else:
                    self._log("info", f"  ✅ Closed {symbol}")

            self._log("info", "🧹 Legacy cleanup complete — ready for scalping!")

        except Exception as e:
            self._log("error", f"Legacy cleanup error: {e}")
            logger.error(f"Legacy cleanup error: {e}")

    # ─── Daily Reset ──────────────────────────────────────────

    def _reset_daily(self, today: date):
        self._trading_date = today
        self._daily_pnl = 0.0
        self._daily_trades = 0
        self._daily_target_reached = False
        self._daily_loss_limit_hit = False
        self._position_peaks.clear()
        self._pending_reconcile.clear()
        self.session_stats["slippage_bps_sum"] = 0.0
        self.session_stats["slippage_bps_count"] = 0

        try:
            account = self._alpaca.get_account()
            self._day_start_equity = account["equity"]
        except Exception:
            self._day_start_equity = self._initial_capital

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
        new_preset = preset_for_score(score, scale=self._scale)
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
        except Exception as exc:
            logger.warning("quant regime check failed: %s", exc)

    async def _ai_regime_check(self):
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

                new_symbols = regime.get("focus_symbols", self.focus_symbols)
                new_sectors = regime.get("focus_sectors", self.focus_sectors)
                if new_symbols != self.focus_symbols:
                    self._log("info", f"🔄 AI Focus Shift: {', '.join(new_sectors)} → {', '.join(new_symbols[:5])}...")
                    self.focus_symbols = new_symbols
                    self.focus_sectors = new_sectors

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
                        to_email=self.owner_email,
                        user_id=self._notify_user_id,
                    )

        except Exception as e:
            logger.warning(f"AI regime check failed: {e}")

    # ─── Scalping Strategy ────────────────────────────────────

    async def _run_scalp(self, account: dict, positions: list, pending: list):
        preset = self._preset
        equity = account["equity"]
        cash = account["cash"]
        settled = self._compliance.settled_cash(cash)
        now_et = datetime.now(ET)
        self._sync_regime_playbook_display(now_et)
        active_playbooks = list(self.regime_data.get("active_playbooks") or self._last_active_playbooks)
        active_playbook_tag = ",".join(active_playbooks) if active_playbooks else None

        pending_symbols = [o["symbol"] for o in pending]
        current_symbols = [p["symbol"] for p in positions]
        use_ext = self._use_extended_limit_orders(now_et)

        # ── 1. Manage open positions ────────────────────────────
        for pos in positions:
            symbol = pos["symbol"]
            plpc = pos["unrealized_plpc"]
            pl_usd = pos["unrealized_pl"]
            qty_to_sell = int(pos["qty"])

            if qty_to_sell < 0:
                if symbol in pending_symbols:
                    continue
                self._log("error", f"⚠️ EMERGENCY COVER {symbol}: qty={pos['qty']}")
                snap = self._alpaca.get_snapshot(symbol) or {}
                etif = "day" if use_ext else self._entry_order_tif()
                er = self._executor.buy(
                    symbol,
                    abs(qty_to_sell),
                    snap,
                    99.0,
                    tif=etif,
                    extended_hours=use_ext,
                    reasons=["emergency_short_cover"],
                    ref_price=float(pos.get("current_price") or 0.0),
                )
                if "error" not in er:
                    self._track_for_reconcile(
                        er,
                        kind="buy",
                        symbol=symbol,
                        settled_before=settled,
                        signal_price=float(pos.get("current_price") or 0.0),
                        intended_qty=abs(qty_to_sell),
                    )
                continue
            if qty_to_sell <= 0:
                continue
            if not self._can_sell(symbol):
                continue

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
            exit_tif = "day" if use_ext else self._exit_tif_for_reason(exit_reason)
            res = self._executor.sell(
                symbol,
                qty_to_sell,
                snapshot,
                preset.spread_filter_percent,
                tif=exit_tif,
                extended_hours=use_ext,
                reasons=[exit_reason],
                playbook=active_playbook_tag,
                ref_price=float(pos.get("current_price") or pos.get("avg_entry_price") or 0.0),
            )
            if "error" in res:
                self._log("error", f"Exit failed {symbol}: {res['error']}")
                continue
            self._track_for_reconcile(
                res,
                kind="sell",
                symbol=symbol,
                signal_price=float(pos.get("current_price") or pos.get("avg_entry_price") or 0.0),
                avg_entry_price=float(pos.get("avg_entry_price") or 0.0),
                intended_qty=qty_to_sell,
                exit_pl_usd=float(pl_usd),
            )

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
        # At 30k scale we need more headroom so a single scan-cash snapshot
        # isn't misleading; use a proportional floor.
        min_cash_floor = 100 if self._scale == "3k" else 500
        if settled < min_cash_floor:
            self._log("info", f"💤 Settled cash too low: ${settled:,.2f}")
            return

        entry_threshold = preset.entry_score_threshold
        if time(9, 35) <= now_et.time() < time(10, 5):
            entry_threshold = max(20, entry_threshold - 8)
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
            if symbol_is_earnings_today(symbol, getattr(self, "_earnings_today", {})):
                continue

            try:
                bars = self._alpaca.get_bars(symbol, "5Min", 50)
                if len(bars) < 20:
                    bars = self._alpaca.get_bars(symbol, "1Day", 30)
                    if len(bars) < 14:
                        continue

                closes = [b["close"] for b in bars]
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

            except Exception as exc:
                logger.warning(f"Scan error for {symbol}: {exc}")

        # ── 4. Execute ──────────────────────────────────────────
        scored.sort(key=lambda x: -x[0])
        fast_names = {"TSLA", "NVDA", "AMD", "META", "QQQ", "SMCI", "COIN"}
        for score_val, symbol, price, reasons in scored[:slots]:
            if symbol in pending_symbols:
                continue

            max_value = equity * (preset.max_position_percent / 100)
            min_notional = (
                preset.min_notional_fast if symbol in fast_names
                else preset.min_notional_slow
            )
            buy_power = min(max_value, settled * preset.settled_cash_trade_cap)
            if buy_power < min_notional:
                continue
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
                f"📊 BUY {symbol}: score={score_val} | {' + '.join(reasons)} | "
                f"${price:.2f} × {qty} = ${cost:,.0f}",
            )

            settled_before = settled
            entry_tif = "day" if use_ext else self._entry_order_tif()
            res = self._executor.buy(
                symbol,
                qty,
                snapshot,
                preset.spread_filter_percent,
                tif=entry_tif,
                extended_hours=use_ext,
                score=float(score_val),
                reasons=reasons,
                playbook=active_playbook_tag,
                ref_price=float(ask or price),
            )
            if "error" in res:
                self._log("error", f"Order failed {symbol}: {res['error']}")
                continue
            self._track_for_reconcile(
                res,
                kind="buy",
                symbol=symbol,
                settled_before=settled_before,
                signal_price=float(ask or price),
                intended_qty=qty,
            )
            self._log("buy", f"📨 BUY submitted {qty} × {symbol} @ ~${price:.2f} (${cost:,.0f}) — awaiting fill")
            acct2 = self._alpaca.get_account()
            settled = self._compliance.settled_cash(float(acct2.get("cash") or 0.0))

    # ─── Technical Indicators ──────────────────────────────────

    def _calculate_indicators(self, closes: list) -> dict:
        import numpy as np
        arr = np.array(closes, dtype=float)

        rsi = self._calculate_rsi(arr, 14)

        ema12 = self._ema(arr, 12)
        ema26 = self._ema(arr, 26) if len(arr) >= 26 else self._ema(arr, len(arr))
        macd = ema12[:len(ema26)] - ema26 if len(ema12) >= len(ema26) else ema12 - ema26[:len(ema12)]
        sig = self._ema(macd, 9) if len(macd) >= 9 else self._ema(macd, max(len(macd), 1))
        macd_signal = "bullish" if len(macd) > 0 and len(sig) > 0 and macd[-1] > sig[-1] else "bearish"

        n = min(20, len(arr))
        ma20 = float(np.mean(arr[-n:]))
        std20 = float(np.std(arr[-n:]))
        bb_upper = ma20 + 2 * std20
        bb_lower = ma20 - 2 * std20

        ma50 = float(np.mean(arr[-min(50, len(arr)):])) if len(arr) >= 10 else float(np.mean(arr))

        return {
            "rsi":           rsi,
            "macd_line":     float(macd[-1]) if len(macd) > 0 else 0,
            "macd_signal":   macd_signal,
            "bb_upper":      bb_upper,
            "bb_lower":      bb_lower,
            "bb_middle":     ma20,
            "ma20":          ma20,
            "ma50":          ma50,
            "current_price": float(arr[-1]),
        }

    def _calculate_rsi(self, prices, period: int = 14) -> float:
        import numpy as np
        if len(prices) < 2:
            return 50.0
        deltas = np.diff(prices)
        p = min(period, len(deltas))
        gains = np.where(deltas[-p:] > 0, deltas[-p:], 0.0)
        losses = np.where(deltas[-p:] < 0, -deltas[-p:], 0.0)
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
        ema = np.zeros_like(data, dtype=float)
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
        slip_sum = self.session_stats["slippage_bps_sum"]
        slip_n = self.session_stats["slippage_bps_count"]

        return {
            **self.session_stats,
            "win_rate": (wins / total * 100) if total > 0 else 0,
            "avg_win": (win_sum / wins) if wins > 0 else 0,
            "avg_loss": (loss_sum / losses) if losses > 0 else 0,
            "profit_factor": (win_sum / loss_sum) if loss_sum > 0 else (win_sum if win_sum > 0 else 0),
            "avg_slippage_bps": round(slip_sum / slip_n, 2) if slip_n > 0 else 0.0,
            "daily_pnl": self._daily_pnl,
            "daily_trades": self._daily_trades,
            "daily_target_reached": self._daily_target_reached,
            "preset": self._preset.level,
            "capital_scale": self._scale,
            "compliance": self._compliance.status(),
        }
