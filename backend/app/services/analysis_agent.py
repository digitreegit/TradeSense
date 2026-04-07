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

    def initialize(self):
        """Initialize the AI provider."""
        try:
            if settings.ai_provider == "openai" and settings.openai_api_key:
                import openai
                self.openai_client = openai.OpenAI(api_key=settings.openai_api_key)
                self._initialized = True
                logger.info(f"✅ AI Agent initialized with OpenAI ({settings.openai_model})")

            elif settings.ai_provider == "gemini" and settings.google_api_key:
                from google import genai
                self.gemini_client = genai.Client(api_key=settings.google_api_key)
                self._initialized = True
                logger.info("✅ AI Agent initialized with Google Gemini 2.0 Flash")

            else:
                logger.warning("⚠️ No AI provider configured. Agent will use templates.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize AI Agent: {e}")

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
        elif self.gemini_client:
            return await self._query_gemini(prompt)
        else:
            return self._template_analysis(symbol, market_data)

    async def chat(self, message: str, context: dict = None) -> str:
        """Chat with the AI agent about trading."""
        system_prompt = self._build_system_prompt(context)

        if self.openai_client:
            return await self._query_openai(message, system_prompt)
        elif self.gemini_client:
            return await self._query_gemini(f"{system_prompt}\n\nUser: {message}")
        else:
            return self._template_chat(message)

    async def generate_signals(self, symbols: list, market_data: dict) -> list:
        """Generate trading signals for multiple symbols."""
        prompt = self._build_signal_prompt(symbols, market_data)

        if self.openai_client:
            response = await self._query_openai(prompt)
        elif self.gemini_client:
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
        """Query Google Gemini 2.0 Flash (runs sync SDK in thread pool)."""
        try:
            def _call():
                response = self.gemini_client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt,
                )
                return response.text
            result = await asyncio.get_event_loop().run_in_executor(None, _call)
            return result
        except Exception as e:
            logger.error(f"Gemini query error: {e}")
            return f"AI 분석 중 오류가 발생했습니다: {str(e)}"

    # ─── Prompts ───────────────────────────────────────────────
    def _build_system_prompt(self, context: dict = None) -> str:
        return """You are TradeSense AI, an expert quant trading assistant.
You analyze stocks using technical and fundamental analysis.
You help manage a $1,000 paper trading portfolio on Alpaca Markets.

Guidelines:
- Provide concise, actionable analysis
- Include specific price levels for entry, stop loss, and targets
- Consider risk management (max 20% per position, 2% stop loss)
- Use technical indicators: RSI, MACD, Bollinger Bands, Moving Averages
- Always remind that this is paper trading
- Respond in Korean when the user writes in Korean
- Use emojis for better readability
- Be conservative with a $1,000 account - PDT rule applies (max 3 day trades per 5 days)
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
    async def determine_market_regime(self, news: list[dict]) -> tuple[str, str]:
        """Analyze news sentiment and return (strategy, reasoning)."""
        if not self.is_ready or not news:
            return "momentum", "뉴스가 충분하지 않아 기본 모멘텀 전략을 유지합니다."

        news_text = "\n".join([f"- {n['headline']}" for n in news])
        
        prompt = f"""
        당신은 상위 1% 퀀트 분석가입니다. 아래 뉴스 헤드라인들을 읽고 현재 시장 분위기를 한 문장으로 요약한 뒤, 최적의 전략을 선택하세요.
        
        뉴스:
        {news_text}
        
        응답 형식 (반드시 이 JSON 형식으로만 답변하세요):
        {{
            "strategy": "momentum" 또는 "mean-reversion",
            "reasoning": "현재 ~~한 상황이므로 ~~한 전략으로 대응합니다."
        }}
        """
        
        try:
            import json
            response = self.model.generate_content(prompt)
            data = json.loads(response.text.strip().replace('```json', '').replace('```', ''))
            return data.get("strategy", "momentum"), data.get("reasoning", "시장 흐름에 따라 전략을 운용합니다.")
        except Exception:
            return "momentum", "시장 데이터 분석을 통해 전략을 최적화합니다."



# Singleton
analysis_agent = AnalysisAgent()
analysis_agent.initialize()  # Initialize immediately at import time
