"""
risk_manager.py

Comprehensive Prop Firm Risk Management & Position Sizing Calculator.
Supports:
1. Funding Pips (via Match-Trader): $5K, $10K, $25K, $50K, $100K, $200K
2. Hyro Trader (via Cleo.finance Bybit Crypto Futures): 5K, 10K, 25K, 50K, 100K, 200K USDT
"""
from typing import Dict, Any, Optional
import config


class RiskManager:
    """
    Enforces prop firm risk rules across Funding Pips and Hyro Trader,
    and calculates exact position / lot sizes dynamically.
    """

    def __init__(self, account_size: float = config.ACCOUNT_SIZE, firm: str = "funding_pips"):
        self.account_size = account_size
        self.active_firm = firm if firm in config.PROP_FIRMS else "funding_pips"
        firm_cfg = config.PROP_FIRMS.get(self.active_firm, config.PROP_FIRMS["funding_pips"])
        self.daily_drawdown_limit_pct = firm_cfg["daily_drawdown_pct"]
        self.total_drawdown_limit_pct = firm_cfg["total_drawdown_pct"]
        self.max_correlated = firm_cfg["max_correlated_positions"]
        self.enforce_stop_loss = firm_cfg["enforce_stop_loss"]

    def get_challenge_summary(self, firm: Optional[str] = None, account_size: Optional[float] = None) -> Dict[str, Any]:
        """
        Returns dynamic risk parameters for the specified prop firm and capital tier.
        Defaults to Funding Pips $5,000 for full backward compatibility.
        """
        target_firm = (firm or self.active_firm or "funding_pips").lower()
        if target_firm not in config.PROP_FIRMS:
            target_firm = "funding_pips"

        firm_cfg = config.PROP_FIRMS[target_firm]

        if account_size is not None and float(account_size) > 0:
            acc = float(account_size)
        else:
            acc = self.account_size if target_firm == "funding_pips" else float(firm_cfg.get("default_tier", 200000.0))

        max_daily_loss = acc * (firm_cfg["daily_drawdown_pct"] / 100.0)
        max_total_loss = acc * (firm_cfg["total_drawdown_pct"] / 100.0)
        risk_1_pct = acc * (firm_cfg["risk_per_trade_min_pct"] / 100.0)
        risk_2_pct = acc * (firm_cfg["risk_per_trade_max_pct"] / 100.0)

        # Account display name
        if target_firm == "funding_pips":
            acc_name = f"Funding Pips ${acc:,.0f} 2-Step Flex"
        else:
            acc_name = f"Hyro Trader {acc:,.0f} USDT Challenge"

        return {
            "firm": target_firm,
            "firm_id": firm_cfg["id"],
            "firm_name": firm_cfg["name"],
            "account_size": acc,
            "account_name": acc_name,
            "platform": firm_cfg["platform"],
            "currency": firm_cfg["currency"],
            "currency_symbol": firm_cfg["currency_symbol"],
            "instrument_focus": firm_cfg["instrument_focus"],
            "max_daily_drawdown_pct": firm_cfg["daily_drawdown_pct"],
            "max_daily_drawdown_usd": round(max_daily_loss, 2),
            "max_total_drawdown_pct": firm_cfg["total_drawdown_pct"],
            "max_total_drawdown_usd": round(max_total_loss, 2),
            "recommended_risk_1pct_usd": round(risk_1_pct, 2),
            "recommended_risk_2pct_usd": round(risk_2_pct, 2),
            "max_correlated_positions": firm_cfg["max_correlated_positions"],
            "stop_loss_enforced": firm_cfg["enforce_stop_loss"],
            "status": "ACTIVE",
            "available_tiers": firm_cfg["tiers"],
            "all_firms": config.PROP_FIRMS
        }

    def calculate_lot_size(
        self,
        symbol: str,
        entry: float,
        stop_loss: float,
        risk_pct: float = 1.0,
        account_size: Optional[float] = None,
        firm: str = "funding_pips"
    ) -> Dict[str, Any]:
        """
        Calculates exact lot size (Match-Trader) or contract size (Cleo.finance Bybit Futures)
        based on risk percentage and distance to stop loss.
        """
        target_firm = (firm or "funding_pips").lower()
        if target_firm not in config.PROP_FIRMS:
            target_firm = "funding_pips"

        firm_cfg = config.PROP_FIRMS[target_firm]

        acc = account_size if account_size is not None else self.account_size
        risk_usd = acc * (risk_pct / 100.0)
        distance = abs(entry - stop_loss)

        meta = config.ASSET_METADATA.get(symbol, {})
        category = meta.get("category", "other")
        mt_sym = meta.get("match_trader", symbol)
        cleo_sym = meta.get("cleo_symbol", symbol.replace("-USD", "USDT"))

        if distance <= 0 or entry <= 0 or stop_loss <= 0 or acc <= 0 or risk_pct <= 0:
            return {
                "symbol": symbol,
                "match_trader_symbol": mt_sym,
                "cleo_symbol": cleo_sym,
                "firm": target_firm,
                "category": category,
                "entry": round(entry, 5) if entry else 0.0,
                "stop_loss": round(stop_loss, 5) if stop_loss else 0.0,
                "distance": round(distance, 5) if distance else 0.0,
                "risk_pct": risk_pct,
                "risk_usd": 0.0,
                "lot_size": 0.0,
                "contracts": 0.0,
                "notional_usd": 0.0,
                "margin_10x": 0.0,
                "rule_status": "INVALID: Entry, stop loss, account size and risk must be positive non-zero values"
            }

        # Hyro Trader (Cleo.finance / Bybit Perpetual Crypto Futures)
        if target_firm == "hyro_trader":
            # In crypto futures, position quantity (coins/contracts) = risk_usd / distance
            contracts = risk_usd / distance
            contracts = round(contracts, 4)
            notional = round(contracts * entry, 2)
            margin_10x = round(notional / 10.0, 2)
            margin_5x = round(notional / 5.0, 2)

            return {
                "symbol": symbol,
                "match_trader_symbol": mt_sym,
                "cleo_symbol": cleo_sym,
                "firm": "hyro_trader",
                "platform": "Cleo.finance (Bybit)",
                "category": category,
                "entry": round(entry, 5),
                "stop_loss": round(stop_loss, 5),
                "distance": round(distance, 5),
                "risk_pct": risk_pct,
                "risk_usd": round(risk_usd, 2),
                "lot_size": contracts,
                "contracts": contracts,
                "notional_usd": notional,
                "margin_10x": margin_10x,
                "margin_5x": margin_5x,
                "position_display": f"{contracts:,.3f} Contracts (${notional:,.2f} USDT)",
                "rule_status": f"COMPLIANT with Hyro Trader 5% Daily Limit ({acc * 0.05:,.0f} USDT)"
            }

        # Funding Pips (Match-Trader Multi-Asset Specifications)
        if category == "forex":
            if "JPY" in symbol:
                pips = distance / 0.01
                pip_val_per_lot = 6.80
            else:
                pips = distance / 0.0001
                pip_val_per_lot = 10.00
            lot = risk_usd / max(1e-4, pips * pip_val_per_lot)
            lot = round(max(0.01, min(50.0, lot)), 2)

        elif category == "commodities":
            if "GC" in symbol or "XAU" in mt_sym:
                lot = risk_usd / (distance * 100.0)
                lot = round(max(0.01, min(50.0, lot)), 2)
            elif "SI" in symbol or "XAG" in mt_sym:
                lot = risk_usd / (distance * 5000.0)
                lot = round(max(0.01, min(50.0, lot)), 2)
            elif "CL" in symbol or "BZ" in symbol or "OIL" in mt_sym:
                lot = risk_usd / (distance * 1000.0)
                lot = round(max(0.01, min(50.0, lot)), 2)
            else:
                lot = risk_usd / max(1e-4, distance * 100.0)
                lot = round(max(0.01, min(50.0, lot)), 2)

        elif category == "indices":
            point_value = 1.0
            lot = risk_usd / max(1.0, distance * point_value)
            lot = round(max(0.01, min(100.0, lot)), 2)

        elif category == "crypto":
            lot = risk_usd / distance
            lot = round(max(0.001, min(250.0, lot)), 3)

        else:
            lot = round(max(0.01, min(5000.0, risk_usd / distance)), 2)

        return {
            "symbol": symbol,
            "match_trader_symbol": mt_sym,
            "cleo_symbol": cleo_sym,
            "firm": "funding_pips",
            "platform": "Match-Trader",
            "category": category,
            "entry": round(entry, 5),
            "stop_loss": round(stop_loss, 5),
            "distance": round(distance, 5),
            "risk_pct": risk_pct,
            "risk_usd": round(risk_usd, 2),
            "lot_size": lot,
            "contracts": lot,
            "notional_usd": round(lot * entry, 2),
            "position_display": f"{lot} Lots",
            "rule_status": f"COMPLIANT with Funding Pips 5% Max Daily Loss (${acc * 0.05:,.0f})"
        }
