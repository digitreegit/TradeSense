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

    # Models to try in order — newest verified first
    GEMINI_MODEL_CANDIDATES = [
        "gemini-2.0-flash-001",
        "gemini-2.0-flash",
        "gemini-1.5-flash-002",
        "gemini-1.5-flash-001",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]

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

        prompt = f"{system_prompt}{context_str}\n\nUser Question: {message}\n\nProvide a helpful, detailed, context-aware response in Korean. Use emojis and formatting."

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
            return f"AI 분석 중 오류가 발생했습니다: {str(e)}"

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
                return "⚠️ 현재 AI 사용량이 많아 할당량이 일시적으로 소진되었습니다. 잠시 후(약 1분 뒤) 다시 질문해 주세요."
            logger.error(f"Gemini query error: {error_str}")
            return f"AI 분석 중 오류가 발생했습니다: {error_str}"

    def _call_legacy_sdk(self, prompt: str) -> str:
        """Call Gemini using the legacy google-generativeai SDK with auto model fallback."""
        # If we already found a working model, use it
        if self.gemini_client:
            response = self.gemini_client.generate_content(prompt)
            return response.text
        
        # Otherwise try each model candidate
        last_error = None
        for model_name in self.GEMINI_MODEL_CANDIDATES:
            try:
                model = self._gemini_genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                # Success! Save this model for future calls
                self.gemini_client = model
                logger.info(f"✅ Found working Gemini model: {model_name}")
                return response.text
            except Exception as e:
                last_error = e
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
- Respond in Korean when the user writes in Korean.
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

Please provide the analysis in Korean with clear formatting and emojis."""

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
        return f"""📊 **{symbol} 분석 리포트** (Template Mode)

🔹 기술적 분석:
  • RSI (14): 분석을 위해 AI API 키를 설정해주세요
  • MACD: API 연결 후 실시간 분석 가능

💡 AI 분석을 활성화하려면:
  1. .env 파일에 OPENAI_API_KEY 또는 GOOGLE_API_KEY를 설정하세요
  2. 서버를 재시작하세요

⚠️ 현재 Paper Trading 모드로 실행 중입니다."""

    def _template_chat(self, message: str) -> str:
        return f"""알겠습니다! "{message}"에 대해 답변드립니다.

현재 AI API가 연결되지 않아 템플릿 모드로 응답합니다.

💡 OpenAI GPT-4o 또는 Google Gemini API 키를 .env 파일에 설정하면
더 정확한 AI 분석을 받으실 수 있습니다.

설정 방법:
1. OPENAI_API_KEY=sk-... 또는
2. GOOGLE_API_KEY=... 를 .env에 추가
3. AI_PROVIDER=openai 또는 gemini로 선택"""

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
        "reasoning": "뉴스가 충분하지 않아 기본 대형 기술주 중심으로 운용합니다.",
        "risk_level": "moderate",
        "max_position_percent": 20,
        "stop_loss_percent": 2,
        "focus_sectors": ["tech_software", "tech_ai"],
        "focus_symbols": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AMD", "TSLA"],
    }

    async def determine_market_regime(self, news: list[dict]) -> dict:
        """Analyze news → strategy, risk, AND which sectors/stocks to focus on."""
        if not self.is_ready or not news:
            return dict(self.DEFAULT_REGIME)

        news_text = "\n".join([f"- {n['headline']}" for n in news])
        sector_desc = "\n".join([f"  - {k}: {', '.join(v)}" for k, v in self.SECTOR_UNIVERSE.items()])

        prompt = f"""당신은 세계 최고의 매크로 퀀트 전략가입니다. 아래 뉴스를 분석하여:
1. 시장 매크로 국면을 진단하고
2. 어떤 섹터/종목에 집중해야 하는지 추천하세요.

핵심 판단 기준:
- 지정학적 위기 (전쟁, 테러) → defense, energy_oil, gold_safe 집중
- 전쟁 종료/평화 → energy_clean, consumer, tech_software 회복주 집중
- AI/반도체 호재 → tech_ai, semiconductor 집중
- 금리 인하 → tech_software, tech_cloud, ev_auto 집중
- 금리 인상/인플레 → financial, energy_oil, gold_safe 집중
- 팬데믹/보건 위기 → healthcare 집중, 리스크 낮춤
- 경기 침체 → gold_safe, consumer, 방어적 운용

사용 가능한 섹터와 종목:
{sector_desc}

뉴스:
{news_text}

반드시 아래 JSON 형식으로만 답변하세요:
{{
    "strategy": "momentum" 또는 "mean-reversion",
    "reasoning": "현재 ~~뉴스로 인해 ~~섹터에 집중합니다.",
    "risk_level": "low" / "moderate" / "aggressive",
    "max_position_percent": 10~30,
    "stop_loss_percent": 1~5,
    "focus_sectors": ["sector1", "sector2"],
    "focus_symbols": ["SYM1", "SYM2", "SYM3", "SYM4", "SYM5", "SYM6", "SYM7", "SYM8"]
}}

focus_symbols는 위 섹터 목록에 있는 종목 중 8개를 고르세요. 최소 2개 섹터에서 분산 선택하세요."""
        
        response_text = ""
        try:
            if self.openai_client:
                response_text = await self._query_openai(prompt)
            elif self.gemini_client:
                response_text = await self._query_gemini(prompt)

            import json
            import re
            match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                
                all_valid = set()
                for syms in self.SECTOR_UNIVERSE.values():
                    all_valid.update(syms)
                
                focus_symbols = [s for s in data.get("focus_symbols", []) if s in all_valid]
                if len(focus_symbols) < 4:
                    focus_symbols = list(self.DEFAULT_REGIME["focus_symbols"])
                    
                focus_sectors = [s for s in data.get("focus_sectors", []) if s in self.SECTOR_UNIVERSE]
                if not focus_sectors:
                    focus_sectors = list(self.DEFAULT_REGIME["focus_sectors"])

                # Calculate Aggregate Market Score
                scores = data.get("market_scores", {"war": 50, "earnings": 50, "fed": 50, "gold": 50, "crypto": 50, "others": 50})
                
                # Weigh scores (lower score = higher risk for some, but let's keep it simple: 100 = Excellent, 0 = Dangerous)
                # For common logic: 100 is "Bullish/Stable", 0 is "Bearish/Crisis"
                avg_score = sum(scores.values()) / len(scores)

                if avg_score >= 80: level = "EXCELLENT"
                elif avg_score >= 60: level = "GOOD"
                elif avg_score >= 40: level = "NORMAL"
                elif avg_score >= 20: level = "BAD"
                else: level = "DANGEROUS"

                return {
                    "strategy": data.get("strategy", "momentum"),
                    "reasoning": data.get("reasoning", "시장 흐름에 따라 전략을 운용합니다."),
                    "risk_level": data.get("risk_level", "moderate"),
                    "market_score": round(avg_score, 1),
                    "market_level": level,
                    "market_scores": scores,
                    "max_position_percent": data.get("max_position_percent", 20),
                    "stop_loss_percent": data.get("stop_loss_percent", 2),
                    "focus_sectors": focus_sectors,
                    "focus_symbols": focus_symbols,
                }
        except Exception as e:
            logger.warning(f"AI regime analysis failed: {e}")
            
        return dict(self.DEFAULT_REGIME)



# Singleton
analysis_agent = AnalysisAgent()
analysis_agent.initialize()  # Initialize immediately at import time
