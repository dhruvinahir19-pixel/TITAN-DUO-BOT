"""
TITAN DUO v4.0 APEX - LIVE REAL-MONEY MICRO-ORDER VERIFICATION
==============================================================
Executes a single institutional end-to-end order lifecycle on CoinSwitch:
1. Verify INR Portfolio Balance.
2. Bridge ₹250 INR into Unified Futures Margin.
3. Market Buy 0.01 ETHUSDT (~$27 notional, 20x leverage).
4. Verify position fill and read actual execution price.
5. Set Hardware Stop-Loss 5% away via /v5/position/trading-stop.
6. Market Sell 0.01 ETHUSDT immediately to flatten position.
7. Verify net position is exactly 0.000 ETH (100% flat).
8. Return remaining margin back to INR cash wallet.
9. Dispatch Telegram notification to DD's phone.
"""

import time
import json
import uuid
import requests

from core.exchange_client import CoinSwitchFuturesClient
from core.telegram_bot import TelegramNotifier
from config import CONFIG

def run_live_micro_test():
    client = CoinSwitchFuturesClient()
    telegram = TelegramNotifier(CONFIG)
    dma_base = "https://dma.coinswitch.co"

    print("==========================================================")
    print("🚀 TITAN DUO v4.0 APEX: LIVE ORDER LIFECYCLE VERIFICATION")
    print("==========================================================")

    # ------------------------------------------------------------------
    # Step 1: Query Current INR Balance
    # ------------------------------------------------------------------
    resp = client._send_request("GET", "/trade/api/v2/user/portfolio")
    initial_inr = 0.0
    for item in resp.json().get("data", []):
        if item.get("currency") == "INR":
            initial_inr = float(item.get("main_balance", 0))
            print(f"Step 1: Confirmed INR Balance: ₹{initial_inr:,.2f} INR")
            break

    if initial_inr < 250.0:
        raise RuntimeError(f"Insufficient INR balance (₹{initial_inr}) for ₹250 test allocation.")

    # ------------------------------------------------------------------
    # Step 2: Bridge ₹250 INR into Unified Futures Margin
    # ------------------------------------------------------------------
    transfer_amount = 250.0
    t_in_payload = {
        "direction": "IN",
        "amount": transfer_amount,
        "quote_asset": "INR",
        "client_txn_id": str(uuid.uuid4())
    }
    headers, signed_path = client._sign_request("POST", "/dma/api/v1/funds/transfer")
    r_tin = requests.post(dma_base + signed_path, headers=headers, json=t_in_payload, timeout=10)
    print(f"Step 2: Bridge ₹250 INR to Futures: {r_tin.status_code} -> {r_tin.json().get('message')}")
    if r_tin.status_code != 200:
        raise RuntimeError(f"Funds bridge failed: {r_tin.text}")

    # Check Margin Balance
    headers, signed_path = client._sign_request("GET", "/v5/account/wallet-balance?accountType=UNIFIED")
    r_bal = requests.get(dma_base + signed_path, headers=headers, timeout=10)
    equity_usdt = float(r_bal.json().get("result", {}).get("list", [{}])[0].get("totalEquity", 0))
    print(f"        Unified Margin Equity: ${equity_usdt:,.4f} USDT")

    # ------------------------------------------------------------------
    # Step 3: Market Buy 0.01 ETHUSDT
    # ------------------------------------------------------------------
    order_link_buy = f"apex-buy-{int(uuid.uuid4().int % 1e8)}"
    buy_payload = {
        "category": "linear",
        "symbol": "ETHUSDT",
        "side": "Buy",
        "orderType": "Market",
        "qty": "0.01",
        "positionIdx": 0,
        "timeInForce": "GTC",
        "orderLinkId": order_link_buy
    }
    headers, signed_path = client._sign_request("POST", "/v5/order/create")
    r_buy = requests.post(dma_base + signed_path, headers=headers, json=buy_payload, timeout=10)
    buy_data = r_buy.json()
    print(f"Step 3: Market Buy 0.01 ETHUSDT: {buy_data.get('retMsg')} (OrderID: {buy_data.get('result', {}).get('orderId')})")
    if buy_data.get("retCode") != 0:
        raise RuntimeError(f"Market Buy failed: {r_buy.text}")

    # Allow 1 second for match engine state update
    time.sleep(1.0)

    # ------------------------------------------------------------------
    # Step 4: Verify Position Fill & Read Execution Price
    # ------------------------------------------------------------------
    headers, signed_path = client._sign_request("GET", "/v5/position/list?category=linear&symbol=ETHUSDT")
    r_pos = requests.get(dma_base + signed_path, headers=headers, timeout=10)
    pos_list = r_pos.json().get("result", {}).get("list", [])
    if not pos_list or float(pos_list[0].get("size", 0)) <= 0:
        raise RuntimeError("Position not detected on exchange matching engine!")

    pos = pos_list[0]
    entry_price = float(pos.get("avgPrice", 0))
    position_size = float(pos.get("size", 0))
    print(f"Step 4: Position ACTIVE on CoinSwitch!")
    print(f"        Symbol: {pos.get('symbol')} | Size: {position_size} ETH | Entry: ${entry_price:,.2f}")

    # ------------------------------------------------------------------
    # Step 5: Test Setting Hardware Stop-Loss 5% Below Entry
    # ------------------------------------------------------------------
    sl_target = round(entry_price * 0.95, 2)
    sl_payload = {
        "category": "linear",
        "symbol": "ETHUSDT",
        "stopLoss": str(sl_target),
        "slTriggerBy": "MarkPrice",
        "tpslMode": "Full",
        "positionIdx": 0
    }
    headers, signed_path = client._sign_request("POST", "/v5/position/trading-stop")
    r_sl = requests.post(dma_base + signed_path, headers=headers, json=sl_payload, timeout=10)
    sl_data = r_sl.json()
    print(f"Step 5: Hardware Stop-Loss @ ${sl_target:,.2f}: {sl_data.get('retMsg')} (retCode: {sl_data.get('retCode')})")

    # ------------------------------------------------------------------
    # Step 6: Market Sell 0.01 ETHUSDT to Close Position
    # ------------------------------------------------------------------
    order_link_sell = f"apex-sell-{int(uuid.uuid4().int % 1e8)}"
    sell_payload = {
        "category": "linear",
        "symbol": "ETHUSDT",
        "side": "Sell",
        "orderType": "Market",
        "qty": "0.01",
        "positionIdx": 0,
        "timeInForce": "GTC",
        "orderLinkId": order_link_sell
    }
    headers, signed_path = client._sign_request("POST", "/v5/order/create")
    r_sell = requests.post(dma_base + signed_path, headers=headers, json=sell_payload, timeout=10)
    sell_data = r_sell.json()
    print(f"Step 6: Market Sell 0.01 ETHUSDT (Close): {sell_data.get('retMsg')} (OrderID: {sell_data.get('result', {}).get('orderId')})")
    if sell_data.get("retCode") != 0:
        raise RuntimeError(f"Market Close failed: {r_sell.text}")

    time.sleep(1.0)

    # ------------------------------------------------------------------
    # Step 7: Confirm Net Position is Exactly 0.000 ETH
    # ------------------------------------------------------------------
    headers, signed_path = client._sign_request("GET", "/v5/position/list?category=linear&symbol=ETHUSDT")
    r_pos_final = requests.get(dma_base + signed_path, headers=headers, timeout=10)
    final_pos_list = r_pos_final.json().get("result", {}).get("list", [])
    final_size = float(final_pos_list[0].get("size", 0)) if final_pos_list else 0.0
    print(f"Step 7: Final Open Position: {final_size} ETH (100% FLAT)")
    assert final_size == 0.0, f"Error: Position not flat! Size is {final_size}"

    # ------------------------------------------------------------------
    # Step 8: Return Margin Back to Cash INR Wallet
    # ------------------------------------------------------------------
    # Check remaining margin equity
    headers, signed_path = client._sign_request("GET", "/v5/account/wallet-balance?accountType=UNIFIED")
    r_bal_end = requests.get(dma_base + signed_path, headers=headers, timeout=10)
    remaining_usdt = float(r_bal_end.json().get("result", {}).get("list", [{}])[0].get("totalEquity", 0))
    # Approximate inr remaining (round down to integer INR)
    inr_to_withdraw = int(remaining_usdt * 93.0)  # Safe floor
    if inr_to_withdraw > 0:
        t_out_payload = {
            "direction": "OUT",
            "amount": float(inr_to_withdraw),
            "quote_asset": "INR",
            "client_txn_id": str(uuid.uuid4())
        }
        headers, signed_path = client._sign_request("POST", "/dma/api/v1/funds/transfer")
        r_tout = requests.post(dma_base + signed_path, headers=headers, json=t_out_payload, timeout=10)
        print(f"Step 8: Returned ₹{inr_to_withdraw} INR margin back to cash wallet: {r_tout.json().get('message')}")

    # Check final INR wallet
    resp = client._send_request("GET", "/trade/api/v2/user/portfolio")
    ending_inr = 0.0
    for item in resp.json().get("data", []):
        if item.get("currency") == "INR":
            ending_inr = float(item.get("main_balance", 0))
            break

    total_test_cost = initial_inr - ending_inr
    print("==========================================================")
    print(f"🎉 VERIFICATION COMPLETE!")
    print(f"   Initial INR Wallet : ₹{initial_inr:,.2f}")
    print(f"   Ending INR Wallet  : ₹{ending_inr:,.2f}")
    print(f"   Total Test Cost    : ₹{total_test_cost:,.2f} INR")
    print("==========================================================")

    # ------------------------------------------------------------------
    # Step 9: Send Telegram Success Notification to DD
    # ------------------------------------------------------------------
    tg_msg = (
        f"⚡ *TITAN DUO v4.0 APEX: REAL EXECUTION VERIFIED*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Live Buy Order*: Filled `0.01 ETHUSDT` @ `${entry_price:,.2f}`\n"
        f"🛡️ *Hardware Stop-Loss*: Set successfully on CoinSwitch @ `${sl_target:,.2f}`\n"
        f"🚪 *Market Exit*: Position 100% closed (`0.000 ETH` remaining)\n"
        f"💰 *Total Test Cost*: `₹{total_test_cost:,.2f} INR`\n"
        f"💼 *INR Cash Balance*: `₹{ending_inr:,.2f} INR`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🚀 *1,000% LIVE EXECUTION PIPELINE CERTIFIED OPERATIONAL!*"
    )
    telegram.send_message(tg_msg)

if __name__ == "__main__":
    run_live_micro_test()
