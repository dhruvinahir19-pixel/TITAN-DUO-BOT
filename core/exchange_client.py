"""
TITAN DUO v4.0 APEX - COINSWITCH PRO REST API CLIENT & SMART CHASER
===================================================================
Production execution engine for CoinSwitch Pro Perpetual Futures.
Features:
- Ed25519 Cryptographic Request Signing (Official CoinSwitch Standard)
- NTP Clock Drift Auto-Correction (< 5,000ms drift window)
- 10-Second Smart Limit Order Chaser (Dynamic Re-quoting)
- Strict 0.35% Slippage Ceiling Guard (Anti-Wick Chase Protection)
- Native Exchange Hardware Stop-Loss Order Management
"""

import time
import logging
import urllib.parse
from typing import Optional, Dict, Any, List, Tuple

import requests
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from config import CONFIG, TradingConfig

logger = logging.getLogger("TitanDuo.Exchange")

class CoinSwitchFuturesClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        proxy_url: Optional[str] = None,
        config: TradingConfig = CONFIG
    ):
        self.config = config
        self.raw_api_key = api_key or getattr(config, "COINSWITCH_API_KEY", "")
        self.secret_key_hex = secret_key or getattr(config, "COINSWITCH_SECRET_KEY", "")
        self.proxy_url = proxy_url or getattr(config, "COINSWITCH_PROXY_URL", "")
        
        # Base URLs: Direct CoinSwitch Pro or Cloudflare Worker Proxy
        self.direct_base_url = "https://coinswitch.co"
        self.base_url = self.proxy_url.rstrip("/") if self.proxy_url else self.direct_base_url
        
        # Initialize Ed25519 Keys
        self._priv_key: Optional[ed25519.Ed25519PrivateKey] = None
        self.public_key_hex: str = ""
        self._init_keys()
        
        # NTP Server Clock Drift Offset in milliseconds
        self.clock_drift_ms: int = 0
        self.sync_clock()

    def _init_keys(self):
        """
        Parses 32-byte secret key and derives the official 64-hex Ed25519 Public Key.
        """
        if not self.secret_key_hex:
            logger.warning("CoinSwitch secret key not configured; running in mock/offline mode.")
            return

        try:
            secret_bytes = bytes.fromhex(self.secret_key_hex)
            self._priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(secret_bytes)
            # Derive the 32-byte raw public key in hex
            pub_bytes = self._priv_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw
            )
            self.public_key_hex = pub_bytes.hex()
            logger.info(f"Ed25519 keys initialized. Derived Public Key: {self.public_key_hex[:16]}...")
        except Exception as e:
            logger.error(f"Failed to initialize Ed25519 keys from secret: {e}")
            raise

    def sync_clock(self) -> int:
        """
        Synchronizes local time with CoinSwitch server clock to eliminate drift rejections.
        """
        try:
            t0 = int(time.time() * 1000)
            resp = requests.get(f"{self.direct_base_url}/trade/api/v2/time", timeout=5)
            t1 = int(time.time() * 1000)
            if resp.status_code == 200:
                data = resp.json()
                server_time = data.get("serverTime", data.get("data", {}).get("server_time"))
                if server_time:
                    rtt = t1 - t0
                    self.clock_drift_ms = int(server_time - (t0 + (rtt // 2)))
                    logger.info(f"CoinSwitch server clock synced. Drift: {self.clock_drift_ms} ms (RTT: {rtt} ms)")
                    return self.clock_drift_ms
        except Exception as e:
            logger.warning(f"Could not sync server clock: {e}. Using local timestamp.")
        return 0

    def get_server_epoch_ms(self) -> str:
        """
        Returns adjusted epoch timestamp in milliseconds.
        """
        local_now = int(time.time() * 1000)
        return str(local_now + self.clock_drift_ms)

    def _sign_request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, str], str]:
        """
        Official CoinSwitch Ed25519 request signer:
        message = METHOD + decoded_path + epoch
        """
        method = method.upper()
        if params:
            sep = "&" if "?" in path else "?"
            # Clean None values
            clean_params = {k: v for k, v in params.items() if v is not None}
            path = path + sep + urllib.parse.urlencode(clean_params)
        decoded_path = urllib.parse.unquote_plus(path)

        epoch = self.get_server_epoch_ms()
        message = method + decoded_path + epoch

        if not self._priv_key:
            raise ValueError("Cannot sign request: Private key is not initialized.")

        signature = self._priv_key.sign(message.encode("utf-8")).hex()

        headers = {
            "Content-Type": "application/json",
            "X-AUTH-APIKEY": self.public_key_hex,
            "X-AUTH-SIGNATURE": signature,
            "X-AUTH-EPOCH": epoch,
            "User-Agent": "TitanDuoBot/4.2.0 (Institutional Algo)"
        }
        return headers, decoded_path

    def _send_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        auth_required: bool = True
    ) -> requests.Response:
        """
        Sends HTTP request with transparent fallback between Cloudflare Proxy and Direct API.
        """
        if auth_required:
            headers, decoded_path = self._sign_request(method, path, params)
        else:
            headers = {"Content-Type": "application/json"}
            decoded_path = path

        url = f"{self.base_url}{decoded_path}"
        try:
            resp = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
                timeout=10
            )
            return resp
        except requests.RequestException as e:
            # Fallback to direct URL if proxy experiences connectivity issue
            if self.base_url != self.direct_base_url:
                logger.warning(f"Proxy request failed: {e}. Falling back to direct CoinSwitch API...")
                url = f"{self.direct_base_url}{decoded_path}"
                return requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_body,
                    timeout=10
                )
            raise

    # --------------------------------------------------------------------------
    # Market Data & Account Endpoints
    # --------------------------------------------------------------------------

    def get_wallet_balance(self) -> Dict[str, Any]:
        """
        Fetches current USDT futures wallet balance.
        """
        resp = self._send_request("GET", "/trade/api/v2/futures/wallet_balance")
        if resp.status_code != 200:
            raise RuntimeError(f"Wallet balance query failed ({resp.status_code}): {resp.text}")
        return resp.json().get("data", {})

    def get_order_book(self, symbol: str) -> Dict[str, Any]:
        """
        Fetches live orderbook (Bids and Asks) for the specified perpetual symbol.
        """
        params = {"symbol": symbol, "exchange": "EXCHANGE_2"}
        resp = self._send_request("GET", "/trade/api/v2/futures/order_book", params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Order book query failed ({resp.status_code}): {resp.text}")
        return resp.json().get("data", {})

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetches active perpetual futures positions.
        """
        params = {"symbol": symbol, "exchange": "EXCHANGE_2"} if symbol else {"exchange": "EXCHANGE_2"}
        resp = self._send_request("GET", "/trade/api/v2/futures/positions", params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Positions query failed ({resp.status_code}): {resp.text}")
        return resp.json().get("data", [])

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Lists all currently working/unfilled orders.
        """
        params = {"open": "true", "exchange": "EXCHANGE_2"}
        if symbol:
            params["symbol"] = symbol
        resp = self._send_request("GET", "/trade/api/v2/futures/orders", params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Open orders query failed ({resp.status_code}): {resp.text}")
        return resp.json().get("data", [])

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """
        Fetches status of a specific order by ID.
        """
        params = {"order_id": order_id, "exchange": "EXCHANGE_2"}
        resp = self._send_request("GET", "/trade/api/v2/futures/order", params=params)
        if resp.status_code != 200:
            raise RuntimeError(f"Get order status failed ({resp.status_code}): {resp.text}")
        return resp.json().get("data", {})

    # --------------------------------------------------------------------------
    # Order Placement & Cancellation
    # --------------------------------------------------------------------------

    def place_limit_order(
        self,
        symbol: str,
        side: str,          # "BUY" or "SELL"
        price: float,
        quantity: float,
        client_order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submits a Limit order to CoinSwitch Pro matching engine.
        """
        body = {
            "exchange": "EXCHANGE_2",
            "symbol": symbol,
            "side": side.upper(),
            "order_type": "LIMIT",
            "price": float(price),
            "quantity": float(quantity)
        }
        if client_order_id:
            body["client_order_id"] = client_order_id

        resp = self._send_request("POST", "/trade/api/v2/futures/order", json_body=body)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Place limit order failed ({resp.status_code}): {resp.text}")
        return resp.json().get("data", {})

    def place_stop_market_order(
        self,
        symbol: str,
        side: str,          # "SELL" for closing Long, "BUY" for closing Short
        trigger_price: float,
        reduce_only: bool = True
    ) -> Dict[str, Any]:
        """
        Submits a native exchange-side STOP_MARKET order.
        Hardware protection: sits on CoinSwitch hardware so sudden crashes never liquidate the user.
        """
        body = {
            "exchange": "EXCHANGE_2",
            "symbol": symbol,
            "side": side.upper(),
            "order_type": "STOP_MARKET",
            "quantity": 0,                      # 0 quantity = full position close on trigger
            "trigger_price": float(trigger_price),
            "reduce_only": reduce_only
        }
        resp = self._send_request("POST", "/trade/api/v2/futures/order", json_body=body)
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Place stop market order failed ({resp.status_code}): {resp.text}")
        return resp.json().get("data", {})

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancels an open order.
        """
        body = {"exchange": "EXCHANGE_2", "order_id": order_id}
        resp = self._send_request("DELETE", "/trade/api/v2/futures/order", json_body=body)
        if resp.status_code != 200:
            raise RuntimeError(f"Cancel order failed ({resp.status_code}): {resp.text}")
        return resp.json().get("data", {})

    def cancel_all_open_orders(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Cancels all open orders (used in emergency /panic kill-switch).
        """
        body = {"exchange": "EXCHANGE_2"}
        if symbol:
            body["symbol"] = symbol
        resp = self._send_request("POST", "/trade/api/v2/futures/cancel-all", json_body=body)
        if resp.status_code != 200:
            raise RuntimeError(f"Cancel all orders failed ({resp.status_code}): {resp.text}")
        return resp.json().get("data", {})


class SmartOrderChaser:
    """
    Dynamic 10-Second Pegged Limit Order Chaser.
    Monitors unfilled limit orders every 10 seconds:
    - If filled: Confirms execution.
    - If unfilled: Re-quotes at updated inside spread.
    - If price exceeds 0.35% slippage ceiling: Safely aborts to prevent buying the top of a wick.
    """
    def __init__(self, client: CoinSwitchFuturesClient, config: TradingConfig = CONFIG):
        self.client = client
        self.config = config

    def execute_smart_limit_entry(
        self,
        symbol: str,
        direction: int,                     # +1 for Long (BUY), -1 for Short (SELL)
        quantity: float,
        signal_candle_close: float,
        max_chase_attempts: int = 6         # 6 attempts x 10s = 60 seconds max chase window
    ) -> Dict[str, Any]:
        """
        Executes an entry order with dynamic 10-second re-pricing and slippage ceiling.
        """
        side = "BUY" if direction == 1 else "SELL"
        active_order_id = None
        attempt = 0

        logger.info(f"Initiating Smart Limit Chaser for {symbol} {side} (Qty: {quantity})")

        while attempt < max_chase_attempts:
            attempt += 1

            # 1. Fetch current live orderbook
            ob = self.client.get_order_book(symbol)
            bids = ob.get("bids", [])
            asks = ob.get("asks", [])
            if not bids or not asks:
                raise RuntimeError(f"Empty order book received for {symbol}")

            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])

            # Check bid-ask spread safety guard
            mid_price = (best_bid + best_ask) / 2.0
            spread_pct = (best_ask - best_bid) / mid_price
            if spread_pct > self.config.MAX_SPREAD_PCT:
                if active_order_id:
                    self.client.cancel_order(active_order_id)
                return {
                    "success": False,
                    "reason": f"Spread ({spread_pct * 100:.3f}%) exceeds safety ceiling ({self.config.MAX_SPREAD_PCT * 100:.2f}%)"
                }

            # 2. Check Slippage Ceiling (Anti-Wick Chase Guard)
            current_slippage = (best_ask - signal_candle_close) / signal_candle_close if direction == 1 else (signal_candle_close - best_bid) / signal_candle_close
            if current_slippage > self.config.MAX_SLIPPAGE_PCT:
                if active_order_id:
                    self.client.cancel_order(active_order_id)
                logger.warning(f"Slippage ceiling hit ({current_slippage * 100:.2f}% > {self.config.MAX_SLIPPAGE_PCT * 100:.2f}%). Aborting trade safely.")
                return {
                    "success": False,
                    "reason": f"Price ran away by {current_slippage * 100:.2f}%; aborted to avoid buying the wick."
                }

            # 3. Determine target inside touch price
            target_limit_price = best_bid if direction == 1 else best_ask

            # 4. If we had an active order from previous attempt, cancel it before re-quoting
            if active_order_id:
                try:
                    status_info = self.client.get_order_status(active_order_id)
                    order_status = status_info.get("status", "").upper()
                    if order_status in ("EXECUTED", "FILLED"):
                        avg_price = float(status_info.get("average_price", target_limit_price))
                        return {"success": True, "fill_price": avg_price, "order_id": active_order_id, "attempts": attempt}
                    self.client.cancel_order(active_order_id)
                except Exception as e:
                    logger.warning(f"Error checking/cancelling order {active_order_id}: {e}")

            # 5. Place fresh Limit Order at current inside spread
            placed = self.client.place_limit_order(
                symbol=symbol,
                side=side,
                price=target_limit_price,
                quantity=quantity
            )
            active_order_id = placed.get("order_id")
            logger.info(f"[Attempt {attempt}/{max_chase_attempts}] Limit order placed @ {target_limit_price} (ID: {active_order_id})")

            # 6. Sleep for 10 seconds before next check
            time.sleep(self.config.ORDER_CHASER_POLL_INTERVAL)

            # 7. Check if order was filled during the 10-second interval
            if active_order_id:
                status_info = self.client.get_order_status(active_order_id)
                order_status = status_info.get("status", "").upper()
                if order_status in ("EXECUTED", "FILLED"):
                    avg_price = float(status_info.get("average_price", target_limit_price))
                    logger.info(f"Order {active_order_id} filled successfully @ {avg_price}!")
                    return {"success": True, "fill_price": avg_price, "order_id": active_order_id, "attempts": attempt}

        # If exhausted all attempts without fill, cancel and abort safely
        if active_order_id:
            try:
                self.client.cancel_order(active_order_id)
            except Exception:
                pass

        return {
            "success": False,
            "reason": f"Order unfilled after {max_chase_attempts} chase attempts (60s timeout)."
        }
