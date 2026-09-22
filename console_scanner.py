"""
console_scanner.py

Interactive CMD Terminal Scanner for QuantumTrader.
Displays either TOP 10 or TOP 30 ranked signals with live 60-second auto-refresh
and Funding Pips Risk Management summary box.
"""
import sys
import os
import time
import argparse
from datetime import datetime
from typing import List, Optional

# UTF-8 Console Encoding
if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from data_engine import MarketDataEngine
from technical_analysis import TechnicalAnalyzer
from signal_engine import SignalEngine, TradeSetup
from risk_manager import RiskManager
import config


class ConsoleTradingDashboard:
    """Rich terminal renderer for trade signals and risk parameters."""

    def __init__(self):
        self.console = Console(width=165)

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

    def print_banner(self, count: int) -> None:
        banner = f"""[bold cyan]
 ==============================================================================
 |                                                                            |
 |                   QUANTUM TRADER — LIVE TERMINAL SCANNER                   |
 |                   Tracking Top {count:02d} Multi-Asset Opportunities                  |
 |                                                                            |
 |   [₿] Crypto  [💱] Forex  [🥇] Commodities  [📊] Indices  [📈] Stocks       |
 |                                                                            |
 ==============================================================================
[/bold cyan]"""
        self.console.print(banner)

    def display_signals(self, signals: List[TradeSetup], limit: int = 30) -> None:
        """Displays color-coded table of top trade signals."""
        if not signals:
            self.console.print("[yellow]⚠️  No signals available. Retrying next cycle...[/yellow]")
            return

        table = Table(
            title=f"🎯 TOP {min(len(signals), limit)} TRADE SIGNALS",
            box=box.DOUBLE_EDGE,
            border_style="green",
            title_style="bold green"
        )
        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Symbol", style="bold white", min_width=18)
        table.add_column("Category", style="cyan", min_width=12)
        table.add_column("Direction", min_width=10)
        table.add_column("Strategy", min_width=18)
        table.add_column("Confidence", justify="right", min_width=11)
        table.add_column("Entry", justify="right", min_width=12)
        table.add_column("Stop", justify="right", min_width=12)
        table.add_column("TP1", justify="right", min_width=12)
        table.add_column("R:R", justify="right", min_width=6)
        table.add_column("Match-Trader", style="magenta", min_width=12)
        table.add_column("Reasoning", min_width=32)

        for i, sig in enumerate(signals[:limit], 1):
            # Direction styling
            if sig.direction == "LONG":
                dir_str = "[bold green]▲ LONG[/bold green]"
            else:
                dir_str = "[bold red]▼ SHORT[/bold red]"

            # Confidence styling
            if sig.confidence >= 80:
                conf_str = f"[bold green]{sig.confidence}%[/bold green]"
            elif sig.confidence >= 65:
                conf_str = f"[yellow]{sig.confidence}%[/yellow]"
            else:
                conf_str = f"[dim]{sig.confidence}%[/dim]"

            table.add_row(
                str(i),
                sig.display_name,
                sig.category.upper(),
                dir_str,
                sig.strategy,
                conf_str,
                self._format_price(sig.entry_price),
                self._format_price(sig.stop_loss),
                self._format_price(sig.take_profit_1),
                f"{sig.risk_reward:.1f}",
                sig.match_trader_symbol or sig.symbol,
                sig.reasoning[:55]
            )

        self.console.print(table)

    def display_risk_summary(self, risk_manager: RiskManager) -> None:
        """Display Funding Pips challenge risk summary panel."""
        summary = risk_manager.get_challenge_summary()
        content = (
            f"[bold]Account:[/bold] [cyan]{summary['account_name']}[/cyan] ({summary['platform']})\n"
            f"[bold]Position Sizing:[/bold] 1-2% risk per trade (${summary['recommended_risk_1pct_usd']:.2f} - ${summary['recommended_risk_2pct_usd']:.2f})\n"
            f"[bold]Max Daily Drawdown:[/bold] [yellow]5% (${summary['max_daily_drawdown_usd']:.2f})[/yellow]\n"
            f"[bold]Max Total Drawdown:[/bold] [red]10% (${summary['max_total_drawdown_usd']:.2f})[/red]\n"
            f"[bold]Max Correlated:[/bold] {summary['max_correlated_positions']} open positions\n"
            f"[bold]Stop Loss:[/bold] [green]ALWAYS ENFORCED[/green]\n"
            f"[bold]Status:[/bold] [bold green]✅ ACTIVE[/bold green]"
        )
        panel = Panel(
            content,
            title="🛡️ RISK MANAGEMENT — FUNDING PIPS $5K CHALLENGE",
            border_style="yellow",
            expand=False
        )
        self.console.print(panel)


def run_scanner(limit: int = 30, interval: int = 60, once: bool = False):
    """Executes live scanner with auto-refresh."""
    console_ui = ConsoleTradingDashboard()
    console_ui.print_banner(limit)

    data_engine = MarketDataEngine()
    analyzer = TechnicalAnalyzer()
    signal_engine = SignalEngine(analyzer=analyzer)
    risk_manager = RiskManager()

    console_ui.console.print(f"[bold green]✓[/bold green] Initializing QuantumTrader Scanner (Tracking {len(config.ALL_WATCHED_SYMBOLS)} symbols)...")
    console_ui.console.print(f"[bold green]✓[/bold green] Display Mode: [bold cyan]Top {limit}[/bold cyan] Setups")
    console_ui.console.print(f"[bold green]✓[/bold green] Refresh Rate: [bold cyan]Every {interval} seconds[/bold cyan]\n")

    try:
        iteration = 1
        while True:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            console_ui.console.print(f"\n[cyan]==============================================================================[/cyan]")
            console_ui.console.print(f"  [bold]📊 QUANTUM SCAN #{iteration}[/bold] — {now_str} (Auto-Refresh: {interval}s)")
            console_ui.console.print(f"[cyan]==============================================================================[/cyan]\n")

            market_data = data_engine.fetch_all_markets()
            setups = signal_engine.scan_all_symbols(market_data, limit=limit)

            console_ui.display_signals(setups, limit=limit)
            console_ui.console.print()
            console_ui.display_risk_summary(risk_manager)

            if once:
                break

            iteration += 1
            console_ui.console.print(f"\n[dim]Next refresh in {interval}s... Press Ctrl+C to exit.[/dim]")
            time.sleep(interval)

    except KeyboardInterrupt:
        console_ui.console.print("\n[yellow]Scanner stopped by user.[/yellow]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="QuantumTrader Terminal Scanner")
    parser.add_argument("--top", type=int, choices=[10, 30], default=30, help="Display Top 10 or Top 30 setups (default: 30)")
    parser.add_argument("--interval", type=int, default=60, help="Refresh interval in seconds (default: 60)")
    parser.add_argument("--once", action="store_true", help="Run scan once and exit")
    args = parser.parse_args()

    run_scanner(limit=args.top, interval=args.interval, once=args.once)
