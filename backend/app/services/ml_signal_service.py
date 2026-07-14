"""
Gradient-boosting intraday direction model + daily retrain + feature drift monitoring.

- **Train:** once per US trading day (weekdays, after ``ML_RETRAIN_AFTER_HOUR_ET``),
  using 5-min bars across a liquid symbol basket; label = forward 3-bar return sign.
- **Serve:** ``playbook_score`` builds the same feature vector as training; compares
  to reference mean/std from the training matrix (max |z| per feature).
- **Drift:** ``warn`` / ``alert`` thresholds from settings — alert zeroes the playbook.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import date, datetime, time as dt_time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pytz
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from app.core.config import settings

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

FEATURE_NAMES: Tuple[str, ...] = (
    "rsi_norm",
    "macd_bull",
    "bb_pct",
    "ret1",
    "ret3",
    "ret5",
    "vol_z",
    "ma10_ratio",
)

TRAIN_SYMBOLS: Tuple[str, ...] = (
    "SPY",
    "QQQ",
    "IWM",
    "XLK",
    "XLE",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMD",
    "META",
)

FORWARD_BARS = 3
MIN_HISTORY = 32
MODEL_FILENAME = "hgb_direction.joblib"

_bundle_lock = threading.Lock()
_cached_bundle: Optional[Dict[str, Any]] = None

_daily_lock = asyncio.Lock()
_last_train_date: Optional[date] = None

_status: Dict[str, Any] = {
    "model_loaded": False,
    "trained_at": None,
    "n_samples": 0,
    "train_auc": None,
    "last_retrain_ok": None,
    "last_retrain_error": None,
    "last_max_drift_z": None,
    "last_drift_level": "unknown",
    "last_proba": None,
}


def _model_path() -> Path:
    p = Path(settings.ml_model_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / MODEL_FILENAME


def _rsi(prices: np.ndarray, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = np.diff(prices)
    p = min(period, len(deltas))
    gains = np.where(deltas[-p:] > 0, deltas[-p:], 0.0)
    losses = np.where(deltas[-p:] < 0, -deltas[-p:], 0.0)
    avg_gain = float(np.mean(gains))
    avg_loss = float(np.mean(losses))
    if avg_loss < 1e-12:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _ema(data: np.ndarray, period: int) -> np.ndarray:
    if len(data) == 0:
        return np.array([0.0])
    alpha = 2.0 / (period + 1)
    ema = np.zeros_like(data, dtype=float)
    ema[0] = data[0]
    for i in range(1, len(data)):
        ema[i] = alpha * data[i] + (1.0 - alpha) * ema[i - 1]
    return ema


def compute_feature_vector(closes: List[float], volumes: List[float]) -> Optional[np.ndarray]:
    c = np.asarray(closes, dtype=float)
    v = np.asarray(volumes, dtype=float)
    if len(c) < MIN_HISTORY or len(v) < MIN_HISTORY:
        return None
    c = c[-MIN_HISTORY:]
    v = v[-MIN_HISTORY:]
    if np.any(c <= 0):
        return None

    rsi = _rsi(c, 14)
    rsi_norm = (rsi - 50.0) / 50.0

    ema12 = _ema(c, 12)
    ema26 = _ema(c, 26) if len(c) >= 26 else _ema(c, min(len(c), 2))
    mlen = min(len(ema12), len(ema26))
    macd_bull = 1.0 if mlen > 0 and ema12[-1] > ema26[-1] else 0.0

    ma20 = float(np.mean(c[-20:]))
    sd20 = float(np.std(c[-20:]))
    bb_pct = 0.5
    if sd20 > 1e-9:
        lo = ma20 - 2 * sd20
        hi = ma20 + 2 * sd20
        bb_pct = float((c[-1] - lo) / (hi - lo + 1e-9))
        bb_pct = max(0.0, min(1.0, bb_pct))

    ret1 = float((c[-1] / c[-2] - 1.0) * 100.0)
    ret3 = float((c[-1] / c[-4] - 1.0) * 100.0) if len(c) >= 4 else 0.0
    ret5 = float((c[-1] / c[-6] - 1.0) * 100.0) if len(c) >= 6 else 0.0

    ma10 = float(np.mean(c[-10:]))
    ma10_ratio = float((c[-1] / ma10 - 1.0) * 100.0) if ma10 > 0 else 0.0

    vol_z = 0.0
    if len(v) >= 12:
        pv = v[-12:-1]
        if np.std(pv) > 1e-9:
            vol_z = float((v[-1] - np.mean(pv)) / (np.std(pv) + 1e-9))

    vec = np.array(
        [rsi_norm, macd_bull, bb_pct, ret1, ret3, ret5, vol_z, ma10_ratio],
        dtype=float,
    )
    return vec


def _build_training_matrix(
    bars: List[dict],
    forward: int = FORWARD_BARS,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    if len(bars) < MIN_HISTORY + forward + 2:
        return None, None
    closes = [float(b["close"]) for b in bars]
    vols = [float(b.get("volume", 0) or 0) for b in bars]
    xs: List[np.ndarray] = []
    ys: List[int] = []
    for t in range(MIN_HISTORY - 1, len(closes) - forward):
        feat = compute_feature_vector(closes[: t + 1], vols[: t + 1])
        if feat is None:
            continue
        fwd = closes[t + forward] / closes[t] - 1.0
        ys.append(1 if fwd > 0.0005 else 0)
        xs.append(feat)
    if len(xs) < 80:
        return None, None
    return np.vstack(xs), np.asarray(ys, dtype=int)


def _load_bundle_unlocked() -> Optional[Dict[str, Any]]:
    global _cached_bundle
    path = _model_path()
    if not path.is_file():
        _cached_bundle = None
        return None
    if _cached_bundle is None:
        try:
            _cached_bundle = joblib.load(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ML model load failed: %s", exc)
            _cached_bundle = None
    return _cached_bundle


def load_bundle() -> Optional[Dict[str, Any]]:
    with _bundle_lock:
        return _load_bundle_unlocked()


def _alpaca_for_training(alpaca_passed: Any) -> Any:
    """Prefer env-based Alpaca singleton for consistent daily training data."""
    try:
        from app.services.alpaca_service import alpaca_service as _svc

        if getattr(_svc, "is_ready", False) and getattr(_svc, "data_client", None):
            return _svc
    except Exception:  # noqa: BLE001
        pass
    return alpaca_passed


def train_pipeline(alpaca: Any, train_day: date) -> Dict[str, Any]:
    """Sync training — run inside ``run_in_executor``."""
    global _cached_bundle
    alpaca = _alpaca_for_training(alpaca)
    all_X: List[np.ndarray] = []
    all_y: List[int] = []
    per_sym_rows: Dict[str, int] = {}

    for sym in TRAIN_SYMBOLS:
        try:
            bars = alpaca.get_bars(sym, "5Min", 400)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ML train skip %s: %s", sym, exc)
            continue
        Xp, yp = _build_training_matrix(bars or [])
        if Xp is None:
            continue
        all_X.append(Xp)
        all_y.append(yp)
        per_sym_rows[sym] = len(yp)

    if not all_X:
        raise RuntimeError("no training rows assembled")

    X = np.vstack(all_X)
    y = np.concatenate(all_y)
    if len(np.unique(y)) < 2:
        raise RuntimeError("degenerate labels")

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    clf = HistGradientBoostingClassifier(
        max_depth=6,
        learning_rate=0.06,
        max_iter=180,
        min_samples_leaf=20,
        l2_regularization=1e-4,
        random_state=42,
    )
    clf.fit(X_train, y_train)
    try:
        proba = clf.predict_proba(X_val)[:, 1]
        auc = float(roc_auc_score(y_val, proba))
    except Exception:  # noqa: BLE001
        auc = None

    ref_mean = X.mean(axis=0)
    ref_std = X.std(axis=0) + 1e-8

    bundle = {
        "model": clf,
        "feature_names": list(FEATURE_NAMES),
        "reference_mean": ref_mean,
        "reference_std": ref_std,
        "trained_at": datetime.now(tz=ET).isoformat(),
        "train_day": train_day.isoformat(),
        "n_samples": int(len(X)),
        "train_auc": auc,
        "per_symbol_rows": per_sym_rows,
    }

    path = _model_path()
    with _bundle_lock:
        joblib.dump(bundle, path)
        _cached_bundle = bundle

    logger.info(
        "ML retrain OK: n=%d auc=%s symbols=%s path=%s",
        len(X),
        auc,
        list(per_sym_rows.keys()),
        path,
    )
    return bundle


def _feature_drift_z(vec: np.ndarray, bundle: Dict[str, Any]) -> Tuple[float, str]:
    ref_m = bundle.get("reference_mean")
    ref_s = bundle.get("reference_std")
    if ref_m is None or ref_s is None:
        return 0.0, "ok"
    z = np.abs(vec - ref_m) / ref_s
    max_z = float(np.max(z))
    warn = float(settings.ml_drift_warn_z)
    alert = float(settings.ml_drift_alert_z)
    if max_z >= alert:
        return max_z, "alert"
    if max_z >= warn:
        return max_z, "warn"
    return max_z, "ok"


def playbook_score(
    price: float,
    indicators: dict,
    bars: list,
    volumes: list,
) -> Tuple[int, List[str]]:
    """Entry playbook hook: probability uplift mapped to 0..28 points."""
    bundle = load_bundle()
    if not bundle or "model" not in bundle:
        return 0, []

    if len(bars) < MIN_HISTORY or len(volumes) < MIN_HISTORY:
        return 0, []

    closes = [float(b["close"]) for b in bars]
    vols = [float(b.get("volume", 0) or 0) for b in bars]
    vec = compute_feature_vector(closes, vols)
    if vec is None:
        return 0, []

    max_z, level = _feature_drift_z(vec, bundle)
    _status["last_max_drift_z"] = round(max_z, 3)
    _status["last_drift_level"] = level

    if level == "alert":
        return 0, [f"MLdrift>{settings.ml_drift_alert_z:.1f}"]

    try:
        clf: HistGradientBoostingClassifier = bundle["model"]
        p = float(clf.predict_proba(vec.reshape(1, -1))[0][1])
    except Exception as exc:  # noqa: BLE001
        logger.warning("ML predict failed: %s", exc)
        return 0, []

    _status["last_proba"] = round(p, 4)
    # Map probability to score; neutral ~0.5
    raw = (p - 0.48) * 160.0
    score = int(max(0.0, min(28.0, raw)))
    if score < 4:
        return 0, []
    reasons = [f"MLp={p:.2f}"]
    if level == "warn":
        reasons.append("MLdrift~")
    return score, reasons


def get_status_dict() -> Dict[str, Any]:
    b = load_bundle()
    out = {**_status}
    if b:
        out["model_loaded"] = True
        out["trained_at"] = b.get("trained_at")
        out["n_samples"] = b.get("n_samples")
        out["train_auc"] = b.get("train_auc")
        out["train_day"] = b.get("train_day")
    else:
        out["model_loaded"] = False
    return out


async def maybe_retrain_daily_async(now_et: datetime, alpaca: Any) -> bool:
    """One training attempt per US trading day (weekdays, after cutoff hour)."""
    global _last_train_date

    if not settings.ml_daily_retrain_enabled:
        return False

    today = now_et.date()
    if now_et.weekday() >= 5:
        return False

    cutoff = dt_time(hour=max(0, min(23, settings.ml_retrain_after_hour_et)), minute=0)
    if now_et.time() < cutoff:
        return False

    async with _daily_lock:
        if _last_train_date == today:
            return False
        ok = False
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: train_pipeline(alpaca, today),
            )
            _status["last_retrain_ok"] = datetime.now(tz=ET).isoformat()
            _status["last_retrain_error"] = None
            ok = True
        except Exception as exc:  # noqa: BLE001
            _status["last_retrain_error"] = str(exc)
            logger.warning("ML daily retrain failed: %s", exc)
        finally:
            _last_train_date = today
        return ok
