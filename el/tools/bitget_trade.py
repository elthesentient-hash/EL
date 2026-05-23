"""Bitget USDT-M futures order executor (demo + live).

Signs requests per Bitget API v2 spec. Defaults to DEMO mode (paptrading=1,
productType=SUSDT-FUTURES, marginCoin=SUSDT) so a misconfigured key cannot
accidentally hit real funds.

Usage:
    python -m el.tools.bitget_trade \
        --symbol ZECUSDT --side long --leverage 10 \
        --margin 25 --entry-price 617.87 --demo
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
import urllib.error
import uuid
from dataclasses import dataclass
from pathlib import Path


BITGET_BASE = "https://api.bitget.com"
ENV_PATH = Path.home() / ".el" / "bitget.env"


@dataclass
class Creds:
    key: str
    secret: str
    passphrase: str


def load_creds() -> Creds:
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    key = env.get("BITGET_API_KEY") or os.environ.get("BITGET_API_KEY", "")
    secret = env.get("BITGET_API_SECRET") or os.environ.get("BITGET_API_SECRET", "")
    passphrase = env.get("BITGET_PASSPHRASE") or os.environ.get("BITGET_PASSPHRASE", "")
    if not all([key, secret, passphrase]):
        raise SystemExit(
            f"Missing creds. Need BITGET_API_KEY, BITGET_API_SECRET, BITGET_PASSPHRASE "
            f"in {ENV_PATH} or env vars."
        )
    return Creds(key, secret, passphrase)


def sign(secret: str, ts: str, method: str, path: str, body: str = "") -> str:
    msg = f"{ts}{method.upper()}{path}{body}"
    digest = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def request(
    creds: Creds, method: str, path: str, body: dict | None = None, demo: bool = True
) -> dict:
    ts = str(int(time.time() * 1000))
    body_str = json.dumps(body, separators=(",", ":")) if body else ""
    signature = sign(creds.secret, ts, method, path, body_str)

    headers = {
        "ACCESS-KEY": creds.key,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": creds.passphrase,
        "Content-Type": "application/json",
        "locale": "en-US",
    }
    if demo:
        headers["paptrading"] = "1"

    url = BITGET_BASE + path
    req = urllib.request.Request(
        url, data=body_str.encode() if body_str else None, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()}


def set_leverage(creds: Creds, symbol: str, leverage: int, demo: bool) -> dict:
    product_type = "SUSDT-FUTURES" if demo else "USDT-FUTURES"
    margin_coin = "SUSDT" if demo else "USDT"
    body = {
        "symbol": symbol,
        "productType": product_type,
        "marginCoin": margin_coin,
        "leverage": str(leverage),
    }
    return request(creds, "POST", "/api/v2/mix/account/set-leverage", body, demo)


def set_margin_mode(creds: Creds, symbol: str, demo: bool, mode: str = "isolated") -> dict:
    product_type = "SUSDT-FUTURES" if demo else "USDT-FUTURES"
    margin_coin = "SUSDT" if demo else "USDT"
    body = {
        "symbol": symbol,
        "productType": product_type,
        "marginCoin": margin_coin,
        "marginMode": mode,
    }
    return request(creds, "POST", "/api/v2/mix/account/set-margin-mode", body, demo)


def place_order(
    creds: Creds,
    symbol: str,
    side: str,
    qty: float,
    leverage: int,
    demo: bool,
    order_type: str = "market",
    price: float | None = None,
) -> dict:
    product_type = "SUSDT-FUTURES" if demo else "USDT-FUTURES"
    margin_coin = "SUSDT" if demo else "USDT"
    body = {
        "symbol": symbol,
        "productType": product_type,
        "marginMode": "isolated",
        "marginCoin": margin_coin,
        "size": f"{qty:.4f}",
        "side": "buy" if side == "long" else "sell",
        "tradeSide": "open",
        "orderType": order_type,
        "force": "gtc",
        "clientOid": uuid.uuid4().hex[:32],
    }
    if order_type == "limit" and price is not None:
        body["price"] = str(price)
    return request(creds, "POST", "/api/v2/mix/order/place-order", body, demo)


def get_account(creds: Creds, symbol: str, demo: bool) -> dict:
    product_type = "SUSDT-FUTURES" if demo else "USDT-FUTURES"
    margin_coin = "SUSDT" if demo else "USDT"
    path = f"/api/v2/mix/account/account?symbol={symbol}&productType={product_type}&marginCoin={margin_coin}"
    return request(creds, "GET", path, None, demo)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", required=True, help="e.g. ZECUSDT")
    p.add_argument("--side", choices=["long", "short"], required=True)
    p.add_argument("--leverage", type=int, required=True)
    p.add_argument("--margin", type=float, required=True, help="Margin in USDT")
    p.add_argument("--entry-price", type=float, required=True, help="Reference price for qty calc")
    p.add_argument("--demo", action="store_true", help="Demo mode (default: live — be careful)")
    p.add_argument("--dry-run", action="store_true", help="Print what would happen, don't send")
    args = p.parse_args()

    creds = load_creds()
    notional = args.margin * args.leverage
    qty = notional / args.entry_price

    print(f"=== Bitget {'DEMO' if args.demo else 'LIVE'} ===")
    print(f"Symbol:   {args.symbol}")
    print(f"Side:     {args.side.upper()}")
    print(f"Leverage: {args.leverage}x")
    print(f"Margin:   ${args.margin}")
    print(f"Notional: ${notional}")
    print(f"Qty:      {qty:.4f}")
    print(f"Entry ref: ${args.entry_price}")

    if args.dry_run:
        print("\n[DRY RUN — no orders sent]")
        return

    print("\n[1/3] Checking account balance…")
    acct = get_account(creds, args.symbol, args.demo)
    print(json.dumps(acct, indent=2))

    print("\n[2/3] Setting leverage…")
    lev_resp = set_leverage(creds, args.symbol, args.leverage, args.demo)
    print(json.dumps(lev_resp, indent=2))

    print("\n[3/3] Placing market order…")
    order_resp = place_order(
        creds, args.symbol, args.side, qty, args.leverage, args.demo
    )
    print(json.dumps(order_resp, indent=2))


if __name__ == "__main__":
    main()
