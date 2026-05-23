"""Bitget USDT-M futures position sizer.

Usage:
    python -m el.tools.position_sizer --equity 25 --leverage 20 --entry 57.5 --mmr 0.005
    python -m el.tools.position_sizer --equity 25 --leverage 20 --entry 57.5 --short
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass


BITGET_TAKER_FEE = 0.0006
BITGET_MAKER_FEE = 0.0002


@dataclass
class SizingResult:
    equity: float
    leverage: float
    entry: float
    side: str
    mmr: float
    notional: float
    qty: float
    liq_price: float
    liq_move_pct: float
    fee_taker_roundtrip: float
    fee_maker_roundtrip: float
    move_to_double_pct: float
    target_2x_price: float
    max_loss: float

    def render(self) -> str:
        arrow = "↓" if self.side == "long" else "↑"
        lines = [
            f"--- Bitget USDT-M Futures Position Sizer ---",
            f"Equity:           ${self.equity:,.2f}",
            f"Leverage:         {self.leverage:g}x  ({self.side.upper()})",
            f"Entry:            ${self.entry:,.6g}",
            f"Maintenance MR:   {self.mmr*100:.3f}%",
            "",
            f"Position notional: ${self.notional:,.2f}",
            f"Contract qty:      {self.qty:.6g}",
            "",
            f"Liquidation price: ${self.liq_price:,.6g}  ({arrow} {self.liq_move_pct*100:.2f}% from entry)",
            f"Max loss at liq:   ${self.max_loss:,.2f}  (≈ your full ${self.equity:.2f} margin)",
            "",
            f"To 2x equity (${self.equity*2:.2f}):",
            f"  Need move:       {self.move_to_double_pct*100:.2f}% in your direction",
            f"  Target price:    ${self.target_2x_price:,.6g}",
            "",
            f"Round-trip fees:   ${self.fee_taker_roundtrip:.4f} (taker) / ${self.fee_maker_roundtrip:.4f} (maker)",
            f"                   = {self.fee_taker_roundtrip/self.equity*100:.2f}% / {self.fee_maker_roundtrip/self.equity*100:.2f}% of equity",
        ]
        return "\n".join(lines)


def size_position(
    equity: float,
    leverage: float,
    entry: float,
    side: str = "long",
    mmr: float = 0.005,
) -> SizingResult:
    if equity <= 0 or leverage <= 0 or entry <= 0:
        raise ValueError("equity, leverage, and entry must all be positive")
    if side not in {"long", "short"}:
        raise ValueError("side must be 'long' or 'short'")

    notional = equity * leverage
    qty = notional / entry

    if side == "long":
        liq_price = entry * (1 - 1 / leverage + mmr)
    else:
        liq_price = entry * (1 + 1 / leverage - mmr)

    liq_move_pct = abs(liq_price - entry) / entry

    fee_taker_roundtrip = notional * BITGET_TAKER_FEE * 2
    fee_maker_roundtrip = notional * BITGET_MAKER_FEE * 2

    move_to_double_pct = 1 / leverage
    if side == "long":
        target_2x_price = entry * (1 + move_to_double_pct)
    else:
        target_2x_price = entry * (1 - move_to_double_pct)

    return SizingResult(
        equity=equity,
        leverage=leverage,
        entry=entry,
        side=side,
        mmr=mmr,
        notional=notional,
        qty=qty,
        liq_price=liq_price,
        liq_move_pct=liq_move_pct,
        fee_taker_roundtrip=fee_taker_roundtrip,
        fee_maker_roundtrip=fee_maker_roundtrip,
        move_to_double_pct=move_to_double_pct,
        target_2x_price=target_2x_price,
        max_loss=equity,
    )


def sweep(equity: float, entry: float, side: str = "long", mmr: float = 0.005) -> str:
    levs = [2, 5, 10, 20, 25, 50, 75, 100]
    rows = [
        f"Leverage | Notional   | Liq price    | Liq move | Move to 2x | Fees (taker rt)",
        f"---------|------------|--------------|----------|------------|----------------",
    ]
    for lev in levs:
        r = size_position(equity, lev, entry, side, mmr)
        rows.append(
            f"{lev:>4g}x    | ${r.notional:>8.2f}  | ${r.liq_price:>10.4g}  | "
            f"{r.liq_move_pct*100:>6.2f}% | {r.move_to_double_pct*100:>8.2f}%  | "
            f"${r.fee_taker_roundtrip:.4f}"
        )
    return "\n".join(rows)


def main() -> None:
    p = argparse.ArgumentParser(description="Bitget USDT-M futures position sizer")
    p.add_argument("--equity", type=float, default=25.0, help="Margin in USDT (default 25)")
    p.add_argument("--leverage", type=float, help="Leverage multiplier. Omit to see full sweep.")
    p.add_argument("--entry", type=float, required=True, help="Entry price")
    p.add_argument("--short", action="store_true", help="Short instead of long")
    p.add_argument("--mmr", type=float, default=0.005, help="Maintenance margin rate (default 0.5%)")
    args = p.parse_args()

    side = "short" if args.short else "long"

    if args.leverage is None:
        print(f"Equity: ${args.equity}  Entry: ${args.entry}  Side: {side.upper()}  MMR: {args.mmr*100}%\n")
        print(sweep(args.equity, args.entry, side, args.mmr))
    else:
        r = size_position(args.equity, args.leverage, args.entry, side, args.mmr)
        print(r.render())


if __name__ == "__main__":
    main()
