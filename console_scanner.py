"""
console_scanner.py

Interactive CMD Terminal Scanner for QuantumTrader.
Displays either TOP 10 or TOP 30 ranked signals with live 60-second auto-refresh
and Dynamic Risk Management summary box for:
- Funding Pips (via Match-Trader): $5K, $10K, $25K, $50K, $100K, $200K
- Hyro Trader (via Cleo.finance Bybit Futures): 5K, 10K, 25K, 50K, 100K, 200K USDT
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
        term_width = None
        try:
            term_width = os.get_terminal_size().columns
        except Exception:
            pass
        effective_width = max(140, term_width) if term_width else 150
        self.console = Console(width=effective_width)

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

    def display_signals(self, signals: List[TradeSetup], limit: int = 30, firm: str = "funding_pips") -> None:
        """Displays color-coded table of top trade signals."""
        if not signals:
            self.console.print("[yellow]⚠️  No signals available. Retrying next cycle...[/yellow]")
            return

        is_hyro = (firm.lower() == "hyro_trader")
        platform_header = "Cleo.finance" if is_hyro else "Match-Trader"

        table = Table(
            title=f"🎯 TOP {min(len(signals), limit)} TRADE SIGNALS ({'HYRO TRADER' if is_hyro else 'FUNDING PIPS'})",
            box=box.DOUBLE_EDGE,
            border_style="green",
            title_style="bold green",
            expand=True
        )
        table.add_column("#", style="dim", width=3, justify="right")
        table.add_column("Symbol", style="bold white", min_width=16)
        table.add_column("Direction", justify="center", min_width=9)
        table.add_column("Strategy", min_width=16)
        table.add_column("Confidence", justify="right", min_width=10)
        table.add_column("Entry", justify="right", min_width=11)
        table.add_column("Stop", justify="right", min_width=11)
        table.add_column("TP1", justify="right", min_width=11)
        table.add_column("R:R", justify="right", min_width=5)
        table.add_column(platform_header, style="magenta", min_width=12)
        table.add_column("Reasoning", min_width=25, overflow="fold")

        for i, sig in enumerate(signals[:limit], 1):
            if sig.direction == "LONG":
                dir_str = "[bold green]▲ LONG[/bold green]"
            else:
                dir_str = "[bold red]▼ SHORT[/bold red]"

            if sig.confidence >= 80:
                conf_str = f"[bold green]{sig.confidence}%[/bold green]"
            elif sig.confidence >= 65:
                conf_str = f"[yellow]{sig.confidence}%[/yellow]"
            else:
                conf_str = f"[dim]{sig.confidence}%[/dim]"

            platform_symbol = sig.cleo_symbol if is_hyro else (sig.match_trader_symbol or sig.symbol)

            table.add_row(
                str(i),
                sig.display_name,
                dir_str,
                sig.strategy,
                conf_str,
                self._format_price(sig.entry_price),
                self._format_price(sig.stop_loss),
                self._format_price(sig.take_profit_1),
                f"{sig.risk_reward:.1f}",
                platform_symbol,
                sig.reasoning
            )

        self.console.print(table)

    def display_risk_summary(self, risk_manager: RiskManager, firm: str = "funding_pips", capital: Optional[float] = None) -> None:
        """Display prop firm risk management summary panel."""
        summary = risk_manager.get_challenge_summary(firm=firm, account_size=capital)
        curr = summary.get("currency", "USD")
        content = (
            f"[bold]Account:[/bold] [cyan]{summary['account_name']}[/cyan] ({summary['platform']})\n"
            f"[bold]Instrument Focus:[/bold] {summary['instrument_focus']}\n"
            f"[bold]Position Sizing:[/bold] 1-2% risk per trade ({summary['recommended_risk_1pct_usd']:,.2f} - {summary['recommended_risk_2pct_usd']:,.2f} {curr})\n"
            f"[bold]Max Daily Drawdown:[/bold] [yellow]5% ({summary['max_daily_drawdown_usd']:,.2f} {curr})[/yellow]\n"
            f"[bold]Max Total Drawdown:[/bold] [red]10% ({summary['max_total_drawdown_usd']:,.2f} {curr})[/red]\n"
            f"[bold]Max Correlated:[/bold] {summary['max_correlated_positions']} open positions\n"
            f"[bold]Stop Loss:[/bold] [green]ALWAYS ENFORCED[/green]\n"
            f"[bold]Status:[/bold] [bold green]✅ ACTIVE[/bold green]"
        )
        title_firm = "HYRO TRADER CRYPTO FUTURES" if firm.lower() == "hyro_trader" else "FUNDING PIPS CHALLENGE"
        panel = Panel(
            content,
            title=f"🛡️ RISK MANAGEMENT — {title_firm} ({summary['account_size']:,.0f} {curr})",
            border_style="yellow",
            expand=False
        )
        self.console.print(panel)


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

            console_ui.display_signals(setups, limit=limit, firm=firm_key)
            console_ui.console.print()
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
    parser.add_argument("--firm", choices=["funding_pips", "hyro_trader"], default="funding_pips", help="Prop firm rules (default: funding_pips)")
    parser.add_argument("--capital", type=float, default=None, help="Challenge account capital (e.g. 5000, 10000, 25000, 50000, 100000, 200000)")
    args = parser.parse_args()

    run_scanner(limit=args.top, interval=args.interval, once=args.once, firm=args.firm, capital=args.capital)
