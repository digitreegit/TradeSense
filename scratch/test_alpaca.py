
from app.services.alpaca_service import alpaca_service
import asyncio

async def test():
    alpaca_service.initialize()
    if not alpaca_service.is_ready:
        print("Alpaca not ready")
        return

    try:
        # Test Portfolio History
        history = alpaca_service.trading_client.get_portfolio_history()
        print(f"History keys: {history.to_dict().keys()}")
        
        # Test Activities
        from alpaca.trading.requests import GetAccountActivitiesRequest
        activities = alpaca_service.trading_client.get_account_activities(GetAccountActivitiesRequest())
        print(f"Activities count: {len(activities)}")
        if len(activities) > 0:
            print(f"Activity sample: {activities[0]}")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(test())
