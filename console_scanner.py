"""
console_scanner.py

Interactive CMD Terminal Scanner for QuantumTrader.
Displays either TOP 10 or TOP 30 ranked signals with live 60-second auto-refresh,
Market Overview box (Gold, Silver, Crude Oil on top), and Prop Firm Risk Management summary.

Maintains the exact 10-column layout and clean Rich formatting of original QuantumTrader:
# | Symbol | Direction | Strategy | Confidence | Entry | Stop | TP1 | R:R | Reasoning
"""
import sys
import os
import time
import argparse
from datetime import datetime
from typing import List, Dict, Any, Optional

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
from dashboard import TradingDashboard, SYMBOL_NAMES
import config


class ConsoleTradingDashboard(TradingDashboard):
    """Console trading dashboard extending TradingDashboard with prop firm banner."""

    def __init__(self):
        term_width = None
        try:
            term_width = os.get_terminal_size().columns
        except Exception:
            pass
        effective_width = term_width if term_width and term_width >= 120 else 120
        self.console = Console(width=effective_width)
        self.logger = self.console

    def print_banner(self, count: int, firm_name: str, capital_str: str) -> None:
        banner = f"""[bold cyan]
 ==============================================================================
 |                                                                            |
 |                   QUANTUM TRADER — LIVE TERMINAL SCANNER                   |
 |                   Tracking Top {count:02d} Multi-Asset Opportunities                  |
 |                   Prop Firm: {firm_name:<18} Account: {capital_str:<15}   |
 |                                                                            |
 |   [₿] Crypto  [💱] Forex  [🥇] Commodities  [📊] Indices  [📈] Stocks       |
 |                                                                            |
 ==============================================================================
[/bold cyan]"""
        self.console.print(banner)

    def display_signals(self, signals: List[TradeSetup], limit: int = 30) -> None:
        """
        Displays color-coded table of top trade signals with EXACT 10 columns:
        # | Symbol | Direction | Strategy | Confidence | Entry | Stop | TP1 | R:R | Reasoning
        """
        if not signals:
            self.console.print("[yellow]⚠️  No signals available. Retrying next cycle...[/yellow]")
            return

        table = Table(
            title=f"🎯 TOP {min(len(signals), limit)} TRADE SIGNALS",
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


def run_scanner(limit: int = 30, interval: int = 60, once: bool = False, firm: str = "funding_pips", capital: Optional[float] = None):
    """Executes live terminal scanner with auto-refresh."""
    firm_key = (firm or "funding_pips").lower()
    firm_cfg = config.PROP_FIRMS.get(firm_key, config.PROP_FIRMS["funding_pips"])

    if capital is None or capital <= 0:
        capital = float(firm_cfg.get("default_tier", 5000.0 if firm_key == "funding_pips" else 200000.0))

    capital_str = f"{capital:,.0f} {firm_cfg['currency']}"

    console_ui = ConsoleTradingDashboard()
    console_ui.print_banner(limit, firm_cfg["name"], capital_str)

    data_engine = MarketDataEngine()
    analyzer = TechnicalAnalyzer()
    signal_engine = SignalEngine(analyzer=analyzer)
    risk_manager = RiskManager(account_size=capital, firm=firm_key)

    console_ui.console.print(f"[bold green]✓[/bold green] Initializing QuantumTrader Scanner (Tracking {len(config.ALL_WATCHED_SYMBOLS)} symbols)...")
    console_ui.console.print(f"[bold green]✓[/bold green] Selected Firm: [bold cyan]{firm_cfg['name']}[/bold cyan] ({firm_cfg['platform']})")
    console_ui.console.print(f"[bold green]✓[/bold green] Account Capital: [bold cyan]{capital_str}[/bold cyan]")
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

            # 1. Market Overview Box (Gold, Silver, Crude Oil on top)
            console_ui.display_market_overview(market_data)
            console_ui.console.print()

            # 2. Top Trade Signals (Exact 10 columns, clean reasoning)
            console_ui.display_signals(setups, limit=limit)
            console_ui.console.print()

            # 3. Risk Management Summary Box
            console_ui.display_risk_summary(risk_manager, firm=firm_key, capital=capital)

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
    parser.add_argument("--firm", choices=["funding_pips", "hyro_trader"], default=None, help="Prop firm rules")
    parser.add_argument("--capital", type=float, default=None, help="Challenge account capital (e.g. 5000, 10000, 25000, 50000, 100000, 200000)")
    args = parser.parse_args()

    firm = args.firm
    capital = args.capital

    if not firm:
        from rich.console import Console
        from rich.prompt import Prompt
        console = Console()
        console.print("\n[bold cyan]=== QUANTUMTRADER CONFIGURATION ===[/bold cyan]")
        choice = Prompt.ask("[bold white]Select Prop Firm (1: Funding Pips, 2: Hyro Trader)[/bold white]", choices=["1", "2"], default="1")
        firm = "funding_pips" if choice == "1" else "hyro_trader"

    if not capital:
        from rich.prompt import IntPrompt
        firm_name = "Funding Pips" if firm == "funding_pips" else "Hyro Trader"
        default_cap = 5000 if firm == "funding_pips" else 200000
        capital = IntPrompt.ask(f"[bold white]Enter Challenge Capital for {firm_name} (5000, 10000, 25000, 50000, 100000, 200000)[/bold white]", choices=["5000", "10000", "25000", "50000", "100000", "200000"], default=default_cap)

    run_scanner(limit=args.top, interval=args.interval, once=args.once, firm=firm, capital=capital)
