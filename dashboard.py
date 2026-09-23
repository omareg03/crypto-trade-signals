"""
dashboard.py

Rich terminal dashboard for QuantumTrader.
Replicates the exact table formatting, Market Overview box (Gold, Silver, Crude Oil on top),
and clean Rich/color formatting of the original QuantumTrader system.
"""
import os
import logging
from typing import List, Dict, Any, Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from signal_engine import TradeSetup
import config

logger = logging.getLogger(__name__)

# Complete display name mappings for monitored symbols
SYMBOL_NAMES = {
    # Commodities
    "GC=F": "Gold", "SI=F": "Silver", "CL=F": "Crude Oil",
    "BZ=F": "Brent Crude", "NG=F": "Natural Gas", "HG=F": "Copper", "PL=F": "Platinum",
    # Indices
    "^GSPC": "S&P 500", "^IXIC": "NASDAQ", "^DJI": "Dow Jones",
    "^RUT": "Russell 2000", "^GDAXI": "DAX 40", "^FTSE": "FTSE 100", "^N225": "Nikkei 225",
    # Forex
    "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "JPY=X": "USD/JPY",
    "CAD=X": "USD/CAD", "AUDUSD=X": "AUD/USD", "CHF=X": "USD/CHF",
    "NZDUSD=X": "NZD/USD", "EURGBP=X": "EUR/GBP", "EURJPY=X": "EUR/JPY",
    "GBPJPY=X": "GBP/JPY", "AUDJPY=X": "AUD/JPY", "EURCAD=X": "EUR/CAD",
    # Crypto
    "BTC-USD": "Bitcoin (BTC)", "ETH-USD": "Ethereum (ETH)",
    "SOL-USD": "Solana (SOL)", "XRP-USD": "XRP (Ripple)",
    "ADA-USD": "Cardano (ADA)", "DOGE-USD": "Dogecoin (DOGE)",
    "AVAX-USD": "Avalanche (AVAX)", "LINK-USD": "Chainlink (LINK)",
    "DOT-USD": "Polkadot (DOT)", "NEAR-USD": "NEAR Protocol",
    "LTC-USD": "Litecoin (LTC)", "BNB-USD": "Binance Coin (BNB)",
    "bitcoin": "Bitcoin (BTC)", "ethereum": "Ethereum (ETH)",
    "solana": "Solana (SOL)", "ripple": "XRP (Ripple)",
    "cardano": "Cardano (ADA)", "dogecoin": "Dogecoin (DOGE)",
    # Stocks
    "NVDA": "NVIDIA", "TSLA": "Tesla", "MSFT": "Microsoft",
    "AAPL": "Apple", "AMZN": "Amazon", "GOOGL": "Alphabet",
    "META": "Meta", "AMD": "AMD", "NFLX": "Netflix",
    "ORCL": "Oracle", "INTC": "Intel", "BA": "Boeing", "DIS": "Disney"
}

CATEGORY_EMOJIS = {
    "commodities": "🥇", "crypto": "₿", "forex": "💱",
    "indices": "📊", "stocks": "📈"
}


class TradingDashboard:
    """Rich terminal-based trading dashboard matching original QuantumTrader layout."""

    def __init__(self):
        term_width = None
        try:
            term_width = os.get_terminal_size().columns
        except Exception:
            pass
        self.console = Console(width=term_width if term_width and term_width >= 120 else 120)
        self.logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def _format_price(price: Optional[float]) -> str:
        if price is None:
            return "N/A"
        if price >= 1000:
            return f"${price:,.2f}"
        elif price >= 1:
            return f"${price:.4f}"
        else:
            return f"${price:.6f}"

    @staticmethod
    def _format_change(change: Optional[float]) -> str:
        if change is None:
            return "[dim]N/A[/dim]"
        if change > 0:
            return f"[green]+{change:.2f}%[/green]"
        elif change < 0:
            return f"[red]{change:.2f}%[/red]"
        else:
            return "[yellow]0.00%[/yellow]"

    @staticmethod
    def _format_volume(vol: Optional[float]) -> str:
        if vol is None:
            return "N/A"
        if vol >= 1_000_000_000:
            return f"${vol/1_000_000_000:.1f}B"
        elif vol >= 1_000_000:
            return f"${vol/1_000_000:.1f}M"
        elif vol >= 1_000:
            return f"${vol/1_000:.1f}K"
        return str(int(vol))

    def display_market_overview(self, market_data: Dict[str, Dict[str, Any]]) -> None:
        """
        Display Market Overview box with Gold, Silver, Crude Oil on top,
        followed by major benchmarks across markets.
        """
        table = Table(
            title="🌐 MARKET OVERVIEW",
            box=box.ROUNDED,
            border_style="cyan",
            title_style="bold cyan"
        )
        table.add_column("Asset", style="bold white", min_width=18)
        table.add_column("Price", style="magenta", justify="right", min_width=14)
        table.add_column("24h Change", justify="right", min_width=12)
        table.add_column("Volume", justify="right", min_width=12)
        table.add_column("Source", style="dim", min_width=10)

        # Gold, Silver, Crude Oil ALWAYS placed at the top as requested
        priority_symbols = [
            "GC=F",     # Gold
            "SI=F",     # Silver
            "CL=F",     # Crude Oil
            "BTC-USD",  # Bitcoin
            "ETH-USD",  # Ethereum
            "EURUSD=X", # EUR/USD
            "^GSPC",    # S&P 500
            "^IXIC",    # NASDAQ
        ]

        for sym in priority_symbols:
            item = market_data.get(sym)
            if not item:
                continue
            display_name = SYMBOL_NAMES.get(sym, item.get("display_name", sym))
            price = self._format_price(item.get("price"))
            change = self._format_change(item.get("change_pct"))
            volume = self._format_volume(item.get("volume"))
            source = item.get("source", "market_feed")
            table.add_row(display_name, price, change, volume, source)

        self.console.print(table)

    def display_market_overview_live(self, all_data: Dict[str, list]) -> None:
        """
        Display color-coded table of all markets from live data.
        Ensures Commodities (Gold, Silver, Crude Oil) appears at the very top.
        """
        self.console.print()

        # Enforce commodities first so Gold, Silver, Crude Oil are on top
        category_order = ["commodities", "crypto", "forex", "indices", "stocks"]
        sorted_categories = [c for c in category_order if c in all_data] + [c for c in all_data if c not in category_order]

        for category in sorted_categories:
            items = all_data.get(category)
            if not items:
                continue

            emoji = CATEGORY_EMOJIS.get(category, "📌")
            table = Table(
                title=f"{emoji} {category.upper()}",
                box=box.ROUNDED,
                border_style="cyan",
                title_style="bold cyan"
            )
            table.add_column("Asset", style="bold white", min_width=18)
            table.add_column("Price", style="magenta", justify="right", min_width=14)
            table.add_column("24h Change", justify="right", min_width=10)
            table.add_column("Volume", justify="right", min_width=12)
            table.add_column("Source", style="dim", min_width=10)

            for item in items:
                if item is None:
                    continue
                symbol = item.get("symbol", "?")
                display_name = SYMBOL_NAMES.get(symbol, symbol.upper())
                price = self._format_price(item.get("price"))
                change = self._format_change(item.get("change_pct"))
                volume = self._format_volume(item.get("volume"))
                source = item.get("source", "")

                table.add_row(display_name, price, change, volume, source)

            self.console.print(table)
            self.console.print()

    def display_signals_live(self, signals: List[TradeSetup], limit: int = 30) -> None:
        """
        Display top trade setups with exact original 10 columns:
        # | Symbol | Direction | Strategy | Confidence | Entry | Stop | TP1 | R:R | Reasoning
        """
        if not signals:
            self.console.print("[yellow]⚠️  No signals generated.[/yellow]")
            return

        table = Table(
            title="🎯 TOP TRADE SIGNALS",
            box=box.DOUBLE_EDGE,
            border_style="green",
            title_style="bold green"
        )
        table.add_column("#", style="dim", width=3)
        table.add_column("Symbol", style="bold white", min_width=16)
        table.add_column("Direction", min_width=8)
        table.add_column("Strategy", min_width=16)
        table.add_column("Confidence", justify="right", min_width=10)
        table.add_column("Entry", justify="right", min_width=12)
        table.add_column("Stop", justify="right", min_width=12)
        table.add_column("TP1", justify="right", min_width=12)
        table.add_column("R:R", justify="right", min_width=6)
        table.add_column("Reasoning", min_width=32)

        for i, sig in enumerate(signals[:limit], 1):
            display_name = sig.display_name or SYMBOL_NAMES.get(sig.symbol, sig.symbol.upper())

            # Color direction
            if sig.direction == "LONG":
                dir_str = "[green]▲ LONG[/green]"
            else:
                dir_str = "[red]▼ SHORT[/red]"

            # Color confidence
            if sig.confidence >= 80:
                conf_str = f"[bold green]{sig.confidence}%[/bold green]"
            elif sig.confidence >= 65:
                conf_str = f"[yellow]{sig.confidence}%[/yellow]"
            else:
                conf_str = f"[dim]{sig.confidence}%[/dim]"

            table.add_row(
                str(i),
                display_name,
                dir_str,
                sig.strategy,
                conf_str,
                self._format_price(sig.entry_price),
                self._format_price(sig.stop_loss),
                self._format_price(sig.take_profit_1),
                f"{sig.risk_reward:.1f}",
                sig.reasoning
            )

        self.console.print(table)

    def display_risk_summary(self, risk_manager, firm: str = "funding_pips", capital: Optional[float] = None) -> None:
        """Display prop firm risk management summary panel."""
        if hasattr(risk_manager, "get_challenge_summary"):
            summary = risk_manager.get_challenge_summary(firm=firm, account_size=capital)
            curr = summary.get("currency", "USD")
            content = (
                f"[bold]Account:[/bold] [cyan]{summary['account_name']}[/cyan] ({summary['platform']})\n"
                f"[bold]Position Sizing:[/bold] 1-2% risk per trade ({summary['recommended_risk_1pct_usd']:,.2f} - {summary['recommended_risk_2pct_usd']:,.2f} {curr})\n"
                f"[bold]Max Daily Drawdown:[/bold] [yellow]5% ({summary['max_daily_drawdown_usd']:,.2f} {curr})[/yellow]\n"
                f"[bold]Max Total Drawdown:[/bold] [red]10% ({summary['max_total_drawdown_usd']:,.2f} {curr})[/red]\n"
                f"[bold]Max Correlated:[/bold] {summary['max_correlated_positions']} positions\n"
                f"[bold]Stop Loss:[/bold] [green]ALWAYS ENFORCED[/green]\n"
                f"[bold]Status:[/bold] [bold green]✅ ACTIVE[/bold green]"
            )
            title = f"🛡️ RISK MANAGEMENT — {summary['account_name'].upper()}"
        else:
            content = (
                f"[bold]Position Sizing:[/bold] 1-2% risk per trade\n"
                f"[bold]Max Daily Drawdown:[/bold] [yellow]5%[/yellow]\n"
                f"[bold]Max Correlated:[/bold] 3 positions\n"
                f"[bold]Stop Loss:[/bold] [green]ALWAYS ENFORCED[/green]\n"
                f"[bold]Status:[/bold] [bold green]✅ ACTIVE[/bold green]"
            )
            title = "🛡️ RISK MANAGEMENT"

        panel = Panel(
            content,
            title=title,
            border_style="yellow",
            expand=False
        )
        self.console.print(panel)
