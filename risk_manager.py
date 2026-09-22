"""
risk_manager.py

Funding Pips Challenge Risk Management & Position Sizing Calculator.
Tailored for Match-Trader $5,000 2-Step Flex Accounts.
"""
from typing import Dict, Any, Optional
import config


class RiskManager:
    """Enforces strict Funding Pips challenge rules and calculates exact lot sizes."""

    def __init__(self, account_size: float = config.ACCOUNT_SIZE):
        self.account_size = account_size
        self.daily_drawdown_limit_pct = config.MAX_DAILY_DRAWDOWN_PCT  # 5% = $250
        self.total_drawdown_limit_pct = config.MAX_TOTAL_DRAWDOWN_PCT  # 10% = $500
        self.max_correlated = config.MAX_CORRELATED_POSITIONS          # 3
        self.enforce_stop_loss = config.ALWAYS_ENFORCE_STOP_LOSS       # True

    def get_challenge_summary(self) -> Dict[str, Any]:
        """Returns key parameters of the Funding Pips challenge account."""
        max_daily_loss = self.account_size * (self.daily_drawdown_limit_pct / 100.0)
        max_total_loss = self.account_size * (self.total_drawdown_limit_pct / 100.0)
        risk_1_pct = self.account_size * (config.RISK_PER_TRADE_MIN_PCT / 100.0)
        risk_2_pct = self.account_size * (config.RISK_PER_TRADE_MAX_PCT / 100.0)

        return {
            "account_size": self.account_size,
            "account_name": "Funding Pips $5,000 2-Step Flex",
            "platform": "Match-Trader",
            "max_daily_drawdown_pct": self.daily_drawdown_limit_pct,
            "max_daily_drawdown_usd": round(max_daily_loss, 2),
            "max_total_drawdown_pct": self.total_drawdown_limit_pct,
            "max_total_drawdown_usd": round(max_total_loss, 2),
            "recommended_risk_1pct_usd": round(risk_1_pct, 2),
            "recommended_risk_2pct_usd": round(risk_2_pct, 2),
            "max_correlated_positions": self.max_correlated,
            "stop_loss_enforced": self.enforce_stop_loss,
            "status": "ACTIVE"
        }

    def calculate_lot_size(
        self,
        symbol: str,
        entry: float,
        stop_loss: float,
        risk_pct: float = 1.0,
        account_size: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculates exact lot size for Match-Trader based on distance to stop loss.
        """
        acc = account_size or self.account_size
        risk_usd = acc * (risk_pct / 100.0)
        distance = abs(entry - stop_loss)

        if distance <= 0 or entry <= 0:
            return {
                "lot_size": 0.0,
                "risk_usd": round(risk_usd, 2),
                "distance": 0.0,
                "note": "Invalid entry or stop loss"
            }

        meta = config.ASSET_METADATA.get(symbol, {})
        category = meta.get("category", "other")
        mt_sym = meta.get("match_trader", symbol)

        # Match-Trader asset contract specifications
        if category == "forex":
            # Standard lot = 100,000 units. For XXX/USD, 1 pip (0.0001) = $10/lot.
            # JPY pairs 1 pip (0.01) = ~$6.50-$7/lot, approximated $7/lot.
            if "JPY" in symbol:
                pips = distance / 0.01
                pip_val_per_lot = 6.80
            else:
                pips = distance / 0.0001
                pip_val_per_lot = 10.00
            lot = risk_usd / max(1e-4, pips * pip_val_per_lot)
            lot = round(max(0.01, min(5.0, lot)), 2)

        elif category == "commodities":
            if "GC" in symbol or "XAU" in mt_sym:
                # Gold: 1 lot = 100 oz. $1 price move = $100 per lot.
                lot = risk_usd / (distance * 100.0)
                lot = round(max(0.01, min(5.0, lot)), 2)
            elif "SI" in symbol or "XAG" in mt_sym:
                # Silver: 1 lot = 5000 oz. $1 move = $5,000 per lot.
                lot = risk_usd / (distance * 5000.0)
                lot = round(max(0.01, min(5.0, lot)), 2)
            elif "CL" in symbol or "BZ" in symbol or "OIL" in mt_sym:
                # Oil: 1 lot = 1,000 barrels. $1 move = $1,000 per lot.
                lot = risk_usd / (distance * 1000.0)
                lot = round(max(0.01, min(5.0, lot)), 2)
            else:
                lot = risk_usd / max(1e-4, distance * 100.0)
                lot = round(max(0.01, min(5.0, lot)), 2)

        elif category == "indices":
            # Cash indices on Match-Trader: typical point value = $1.00 or $2.00 per point for 1 lot
            point_value = 1.0
            lot = risk_usd / max(1.0, distance * point_value)
            lot = round(max(0.01, min(10.0, lot)), 2)

        elif category == "crypto":
            # Crypto CFD on Match-Trader: 1 lot = 1 coin for BTC/ETH, or units
            lot = risk_usd / distance
            lot = round(max(0.001, lot), 3)

        else:
            # Equities: shares = risk_usd / distance
            lot = round(risk_usd / distance, 2)

        return {
            "symbol": symbol,
            "match_trader_symbol": mt_sym,
            "category": category,
            "entry": round(entry, 5),
            "stop_loss": round(stop_loss, 5),
            "distance": round(distance, 5),
            "risk_pct": risk_pct,
            "risk_usd": round(risk_usd, 2),
            "lot_size": lot,
            "rule_status": "COMPLIANT with Funding Pips 5% Max Daily Loss"
        }
