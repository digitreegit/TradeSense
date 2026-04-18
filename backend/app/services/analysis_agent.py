"""
TradeSense - AI Analysis Agent
Uses Gemini 2.0 Flash for stock analysis and trading insights.
"""
import logging
import asyncio
from app.core.config import settings

logger = logging.getLogger(__name__)


class AnalysisAgent:
    """AI-powered stock analysis agent using LLM."""

    def __init__(self):
        self.openai_client = None
        self.gemini_client = None
        self._initialized = False
        self.gemini_version = "new"
        # Rate limiting: minimum 1 second between Gemini calls
        self._last_gemini_call = 0.0
        self._min_call_interval = 1.0
        self._last_response_cache: dict = {}  # prompt_hash -> response

    def initialize(self):
        """Initialize the AI provider."""
        try:
            if settings.ai_provider == "openai" and settings.openai_api_key:
                import openai
                self.openai_client = openai.OpenAI(api_key=settings.openai_api_key)
                self._initialized = True
                logger.info(f"✅ AI Agent initialized with OpenAI ({settings.openai_model})")

            elif settings.ai_provider == "gemini" and settings.google_api_key:
                # Try Legacy SDK first (google-generativeai) — most stable
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=settings.google_api_key)
                    # Try to find a working model
                    self._gemini_genai = genai
                    self.gemini_version = "legacy"
                    self.gemini_client = None  # Will be set on first successful call
                    self._initialized = True
                    # Refresh candidate list from the live API so retired models
                    # (e.g. gemini-1.5-*) don't produce 404s at call time.
                    self._discover_gemini_models()
                    logger.info("✅ AI Agent initialized with Google Gemini (Legacy SDK)")
                except ImportError:
                    try:
                        from google import genai
                        self.gemini_client = genai.Client(api_key=settings.google_api_key)
                        self.gemini_version = "new"
                        self._initialized = True
                        logger.info("✅ AI Agent initialized with Google Gemini (New SDK)")
                    except ImportError:
                        logger.error("❌ No Gemini SDK found. Install google-generativeai or google-genai.")
                
            else:
                logger.warning("⚠️ No AI provider configured. Agent will use templates.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize AI Agent: {e}")

    # Models to try in order — newest generally-available first.
    # NOTE: gemini-1.5-* was retired from v1beta in late 2025, so we prefer
    # 2.5 / 2.0 families. The live list is also fetched dynamically via
    # list_models() (see _discover_gemini_models) when the SDK supports it.
    GEMINI_MODEL_CANDIDATES = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-2.0-flash-001",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]

    def _discover_gemini_models(self) -> None:
        """Query the Gemini API for models that actually support generateContent
        and prepend them to the candidate list. Fails silently on errors."""
        try:
            genai = getattr(self, "_gemini_genai", None)
            if not genai or not hasattr(genai, "list_models"):
                return
            available: list[str] = []
            for m in genai.list_models():
                methods = getattr(m, "supported_generation_methods", None) or []
                if "generateContent" not in methods:
                    continue
                raw = getattr(m, "name", "") or ""
                short = raw.split("/")[-1] if "/" in raw else raw
                if not short or "embedding" in short.lower():
                    continue
                available.append(short)

            if not available:
                return

            def rank(name: str) -> tuple:
                n = name.lower()
                fam = 3
                if "2.5" in n:
                    fam = 0
                elif "2.0" in n:
                    fam = 1
                elif "1.5" in n:
                    fam = 2
                tier = 2
                if "flash" in n and "lite" not in n:
                    tier = 0
                elif "flash-lite" in n or "flash_lite" in n or "lite" in n:
                    tier = 1
                elif "pro" in n:
                    tier = 2
                return (fam, tier, name)

            available.sort(key=rank)
            merged: list[str] = []
            for name in available + self.GEMINI_MODEL_CANDIDATES:
                if name not in merged:
                    merged.append(name)
            self.GEMINI_MODEL_CANDIDATES = merged
            logger.info(
                "Gemini model candidates (live): %s",
                ", ".join(self.GEMINI_MODEL_CANDIDATES[:6]),
            )
        except Exception as e:
            logger.warning(f"Could not list Gemini models: {e}")

    @property
    def is_ready(self) -> bool:
        if not self._initialized:
            self.initialize()
        return self._initialized

    async def analyze_stock(self, symbol: str, market_data: dict) -> str:
        """Generate a comprehensive stock analysis."""
        prompt = self._build_analysis_prompt(symbol, market_data)

        if self.openai_client:
            return await self._query_openai(prompt)
        elif self._initialized and settings.ai_provider == "gemini":
            return await self._query_gemini(prompt)
        else:
            return self._template_analysis(symbol, market_data)

    async def chat(self, message: str, context: dict = None) -> str:
        """Chat with the AI agent about trading."""
        system_prompt = self._build_system_prompt(context)

        # Build a rich, context-aware prompt
        context_str = ""
        if context:
            acc = context.get("account", {})
            pos = context.get("positions", [])
            if acc:
                context_str += f"\n\nCurrent Portfolio:\n- Equity: ${acc.get('equity', 'N/A')}\n- Cash: ${acc.get('cash', 'N/A')}\n- P&L: ${acc.get('profit_loss', 'N/A')} ({acc.get('profit_loss_pct', 'N/A')}%)"
            if pos:
                context_str += f"\n- Open Positions: {len(pos)} stocks"
                for p in pos[:5]:
                    context_str += f"\n  • {p.get('symbol','?')}: {p.get('qty','?')} shares, P&L ${p.get('unrealized_pl','?')}"

        prompt = f"{system_prompt}{context_str}\n\nUser Question: {message}\n\nProvide a helpful, detailed, context-aware response in English. Use emojis and formatting."

        if self.openai_client:
            return await self._query_openai(message, system_prompt)
        elif self._initialized and settings.ai_provider == "gemini":
            return await self._query_gemini(prompt)
        else:
            return self._template_chat(message)

    async def generate_signals(self, symbols: list, market_data: dict) -> list:
        """Generate trading signals for multiple symbols."""
        prompt = self._build_signal_prompt(symbols, market_data)

        if self.openai_client:
            response = await self._query_openai(prompt)
        elif self._initialized and settings.ai_provider == "gemini":
            response = await self._query_gemini(prompt)
        else:
            response = ""

        # Parse signals from response
        return self._parse_signals(response, symbols)

    # ─── LLM Queries ───────────────────────────────────────────
    async def _query_openai(self, user_message: str, system_message: str = None) -> str:
        """Query OpenAI GPT-4o."""
        try:
            messages = []
            if system_message:
                messages.append({"role": "system", "content": system_message})
            messages.append({"role": "user", "content": user_message})

            response = self.openai_client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                temperature=0.7,
                max_tokens=1500,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI query error: {e}")
            return f"AI analysis error: {str(e)}"

    async def _query_gemini(self, prompt: str) -> str:
        """Query Google Gemini with auto model detection and rate limiting."""
        import time
        import hashlib
        
        # Rate limiting
        now = time.time()
        elapsed = now - self._last_gemini_call
        if elapsed < self._min_call_interval:
            prompt_hash = hashlib.md5(prompt[:200].encode()).hexdigest()
            if prompt_hash in self._last_response_cache:
                logger.info("Using cached Gemini response (rate limited)")
                return self._last_response_cache[prompt_hash]
            await asyncio.sleep(self._min_call_interval - elapsed)

        self._last_gemini_call = time.time()

        try:
            def _call():
                if self.gemini_version == "legacy":
                    return self._call_legacy_sdk(prompt)
                else:
                    return self._call_new_sdk(prompt)
                    
            result = await asyncio.get_event_loop().run_in_executor(None, _call)
            
            # Cache successful response
            prompt_hash = hashlib.md5(prompt[:200].encode()).hexdigest()
            self._last_response_cache[prompt_hash] = result
            if len(self._last_response_cache) > 20:
                oldest = next(iter(self._last_response_cache))
                del self._last_response_cache[oldest]
            
            return result
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
                logger.warning("Gemini API quota exhausted, returning friendly message")
                return "⚠️ AI quota is temporarily exhausted. Please try again in about a minute."
            logger.error(f"Gemini query error: {error_str}")
            return f"AI analysis error: {error_str}"

    def _call_legacy_sdk(self, prompt: str) -> str:
        """Call Gemini using the legacy google-generativeai SDK with auto model fallback."""
        # If we already found a working model, try it once; on 404 fall back.
        if self.gemini_client:
            try:
                response = self.gemini_client.generate_content(prompt)
                return response.text
            except Exception as e:
                err = str(e)
                if "404" in err or "NOT_FOUND" in err.upper() or "is not supported" in err:
                    logger.warning(
                        "Cached Gemini model returned 404; re-discovering models."
                    )
                    self.gemini_client = None
                    self._discover_gemini_models()
                else:
                    raise

        last_error = None
        for model_name in self.GEMINI_MODEL_CANDIDATES:
            try:
                model = self._gemini_genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                self.gemini_client = model
                logger.info(f"✅ Found working Gemini model: {model_name}")
                return response.text
            except Exception as e:
                last_error = e
                err = str(e)
                if "404" in err or "NOT_FOUND" in err.upper() or "is not supported" in err:
                    logger.warning(f"Model {model_name} not available, trying next...")
                    continue
                logger.warning(f"Model {model_name} failed: {e}")
                continue

        raise last_error or Exception("No working Gemini model found")

    def _call_new_sdk(self, prompt: str) -> str:
        """Call Gemini using the new google-genai SDK with auto model fallback."""
        last_error = None
        for model_name in self.GEMINI_MODEL_CANDIDATES:
            try:
                response = self.gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                logger.info(f"✅ Found working Gemini model: {model_name}")
                return response.text
            except Exception as e:
                last_error = e
                error_str = str(e)
                if "404" in error_str or "NOT_FOUND" in error_str:
                    logger.warning(f"Model {model_name} not available, trying next...")
                    continue
                else:
                    raise  # Other error (rate limit etc), don't try next model
        
        raise last_error or Exception("No working Gemini model found")

    # ─── Prompts ───────────────────────────────────────────────
    def _build_system_prompt(self, context: dict = None) -> str:
        return """You are TradeSense AI, a micro-scalping specialist for US stocks.

Portfolio Context:
- Capital: $3,000 (Cash Account — NO margin)
- Strategy: Micro-scalp, daily +1% compounding target
- Account type: Cash (PDT-exempt, but must avoid Good Faith Violations)
- T+1 settlement: funds from sells settle next business day

Your core mission:
1. Capital Preservation FIRST: With only $3,000, every dollar matters. Never risk more than 0.3% per trade.
2. Scalp small, consistent gains: Target 0.5-1.0% per trade, accumulate to daily +1%.
3. Macro awareness: Monitor geopolitical risks, earnings, and Fed events to AVOID trading during high-volatility periods.
4. GFV awareness: Remind users about cash settlement rules when relevant.

Guidelines:
- Respond in English unless the user explicitly asks for another language.
- Be specific: give exact entry prices, stop losses, and targets.
- Use emojis for readability.
- Focus on the most liquid stocks (AAPL, MSFT, NVDA, AMD, META, TSLA, SPY, QQQ) for tight spreads.
- This is Paper Trading but treat it as real money for realistic analysis.
"""

    def _build_analysis_prompt(self, symbol: str, market_data: dict) -> str:
        data_str = str(market_data) if market_data else "No data available"
        return f"""Analyze {symbol} stock and provide:
1. Technical Analysis (RSI, MACD, MA, Bollinger Bands)
2. Trend Analysis (short/medium/long term)
3. Key support and resistance levels
4. Trading recommendation with specific entry/exit prices
5. Risk assessment for a $1,000 portfolio

Market Data: {data_str}

Please provide the analysis in English with clear formatting and emojis."""

    def _build_signal_prompt(self, symbols: list, market_data: dict) -> str:
        return f"""Based on the following market data, generate trading signals for these stocks:
Symbols: {', '.join(symbols)}

For each symbol, provide:
- Signal: BUY / SELL / HOLD
- Confidence: HIGH / MEDIUM / LOW
- Entry price
- Stop loss
- Target price
- Reasoning (1 sentence)

Market Data: {str(market_data)}"""

    # ─── Template fallbacks ────────────────────────────────────
    def _template_analysis(self, symbol: str, market_data: dict) -> str:
        return f"""📊 **{symbol} analysis** (Template Mode)

🔹 Technical analysis:
  • RSI (14): set OPENAI_API_KEY or GOOGLE_API_KEY in .env for live AI analysis
  • MACD: available after API is connected

💡 To enable AI:
  1. Add OPENAI_API_KEY or GOOGLE_API_KEY to .env
  2. Restart the server

⚠️ Running in Paper Trading mode."""

    def _template_chat(self, message: str) -> str:
        return f"""Thanks for your message about "{message}".

The AI API is not connected — this is a template response.

💡 Add OpenAI or Google Gemini keys to .env for full analysis:
1. OPENAI_API_KEY=sk-...
2. GOOGLE_API_KEY=...
3. AI_PROVIDER=openai or gemini"""

    def _parse_signals(self, response: str, symbols: list) -> list:
        """Parse trading signals from LLM response."""
        signals = []
        for symbol in symbols:
            if symbol.upper() in response.upper():
                signal = "hold"
                confidence = "low"
                if "BUY" in response.upper():
                    signal = "buy"
                    confidence = "medium"
                elif "SELL" in response.upper():
                    signal = "sell"
                    confidence = "medium"

                signals.append({
                    "symbol": symbol,
                    "signal": signal,
                    "confidence": confidence,
                })
        return signals
    # ─── Stock Universe by Sector ─────────────────────────────
    SECTOR_UNIVERSE = {
        "tech_ai": ["NVDA", "AMD", "AVGO", "MRVL", "SMCI"],
        "tech_software": ["MSFT", "AAPL", "GOOGL", "META", "CRM"],
        "tech_cloud": ["AMZN", "SNOW", "NET", "DDOG", "MDB"],
        "semiconductor": ["TSM", "INTC", "QCOM", "ASML", "KLAC"],
        "energy_oil": ["XOM", "CVX", "COP", "SLB", "OXY"],
        "energy_clean": ["ENPH", "FSLR", "NEE", "PLUG", "BE"],
        "defense": ["LMT", "RTX", "NOC", "GD", "BA"],
        "healthcare": ["UNH", "JNJ", "PFE", "MRNA", "LLY"],
        "financial": ["JPM", "GS", "MS", "BAC", "V"],
        "consumer": ["COST", "WMT", "TGT", "NKE", "SBUX"],
        "ev_auto": ["TSLA", "RIVN", "F", "GM", "LI"],
        "gold_safe": ["GLD", "NEM", "GOLD", "AEM", "WPM"],
    }

    DEFAULT_REGIME = {
        "strategy": "momentum",
        "reasoning": "Insufficient news; defaulting to large-cap tech-focused universe.",
        "risk_level": "moderate",
        "market_score": 50.0,
        "market_level": "NORMAL",
        "market_scores": {"war": 50, "earnings": 50, "fed": 50, "gold": 50, "crypto": 50, "others": 50},
        "max_position_percent": 15,
        "stop_loss_percent": 0.3,
        "focus_sectors": ["tech_software", "tech_ai"],
        "focus_symbols": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AMD", "TSLA"],
    }

    async def determine_market_regime(self, news: list[dict]) -> dict:
        """Analyze news and quantify 6 key indicators into a market score."""
        if not self.is_ready or not news:
            return dict(self.DEFAULT_REGIME)

        news_text = "\n".join([f"- {n['headline']}" for n in news[:15]])
        
        prompt = f"""You are a senior macro quant strategist. Read the news below, quantify current market risk across six dimensions (0–100 each; higher = more favorable/safer for risk-on equities), and propose an optimal tactical tilt.

Dimensions (0–100 each):
1. Geopolitical: peaceful/stable = 100, war/crisis = 0
2. Earnings: positive surprises = 100, major misses = 0
3. Fed Policy: easing/dovish = 100, tightening/hawkish = 0
4. Gold: calm/stable gold = 100, fear-driven spike = 0
5. Crypto: risk-on / strong = 100, crash / risk-off = 0
6. Others (macro data): stable jobs/consumption = 100, deterioration = 0

Sector playbook:
- War / geopolitical stress → tilt defense, energy_oil, gold_safe
- Fed easing → tilt tech_software, tech_cloud, ev_auto
- Positive earnings theme → tilt that sector

Available sectors: {list(self.SECTOR_UNIVERSE.keys())}

News headlines:
{news_text}

Reply with ONLY valid JSON in this exact shape:
{{
    "strategy": "momentum" or "mean-reversion",
    "reasoning": "one-sentence rationale in English",
    "risk_level": "low" / "moderate" / "aggressive",
    "market_scores": {{
        "war": <number>,
        "earnings": <number>,
        "fed": <number>,
        "gold": <number>,
        "crypto": <number>,
        "others": <number>
    }},
    "max_position_percent": <10-25>,
    "stop_loss_percent": <0.2-1.0>,
    "focus_sectors": ["sector1", "sector2"],
    "focus_symbols": ["SYM1", "SYM2", "SYM3", "SYM4", "SYM5", "SYM6", "SYM7", "SYM8"]
}}"""

        try:
            if self.openai_client:
                response_text = await self._query_openai(prompt)
            else:
                response_text = await self._query_gemini(prompt)

            import json
            import re
            match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                
                # Cleanup symbols and sectors
                all_valid = set()
                for syms in self.SECTOR_UNIVERSE.values():
                    all_valid.update(syms)
                
                focus_symbols = [s for s in data.get("focus_symbols", []) if s in all_valid]
                if len(focus_symbols) < 4:
                    focus_symbols = list(self.DEFAULT_REGIME["focus_symbols"])
                    
                focus_sectors = [s for s in data.get("focus_sectors", []) if s in self.SECTOR_UNIVERSE]
                if not focus_sectors:
                    focus_sectors = list(self.DEFAULT_REGIME["focus_sectors"])

                # Calculate Aggregate Market Score (Quantify!)
                scores = data.get("market_scores", self.DEFAULT_REGIME["market_scores"])
                avg_score = sum(scores.values()) / len(scores)

                if avg_score >= 80: level = "EXCELLENT"
                elif avg_score >= 60: level = "GOOD"
                elif avg_score >= 40: level = "NORMAL"
                elif avg_score >= 20: level = "BAD"
                else: level = "DANGEROUS"

                return {
                    "strategy": data.get("strategy", "momentum"),
                    "reasoning": data.get("reasoning", "Operating tactically per current market conditions."),
                    "risk_level": data.get("risk_level", "moderate"),
                    "market_score": round(avg_score, 1),
                    "market_level": level,
                    "market_scores": scores,
                    "max_position_percent": data.get("max_position_percent", 15),
                    "stop_loss_percent": data.get("stop_loss_percent", 0.3),
                    "focus_sectors": focus_sectors,
                    "focus_symbols": focus_symbols,
                }
        except Exception as e:
            logger.warning(f"AI regime analysis failed: {e}")
            
        return dict(self.DEFAULT_REGIME)



# Singleton
analysis_agent = AnalysisAgent()
analysis_agent.initialize()  # Initialize immediately at import time
