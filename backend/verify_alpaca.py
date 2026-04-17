
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add backend to path
sys.path.append(str(Path.cwd()))
load_dotenv(".env")

from alpaca.trading.client import TradingClient
from alpaca.common.exceptions import APIError

def verify_keys():
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    
    print(f"Testing keys...")
    print(f"API Key: {api_key}")
    # print(f"Secret: {secret_key}") # Don't print secret
    
    try:
        client = TradingClient(api_key, secret_key, paper=True)
        acc = client.get_account()
        print(f"✅ Success! Connected to Alpaca.")
        print(f"Account #: {acc.account_number}")
        print(f"Equity: ${acc.equity}")
    except APIError as e:
        print(f"❌ API Error: {e}")
    except Exception as e:
        print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    verify_keys()
