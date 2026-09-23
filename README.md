# 🚀 QuantumTrader v2.0 — Multi-Asset 30-Signal Intelligence System

A high-performance trading intelligence scanner tailored for **Funding Pips $5,000 Challenge (Match-Trader)** and **Coinbase**. 
Provides continuous real-time market analysis, dynamic technical scoring, Risk:Reward management, and responsive live dashboards across desktop and mobile.

---

## 🌟 Key Features

1. **Top 30 Multi-Asset Coverage**:
   - **Crypto (24/7)**: Bitcoin (BTC), Ethereum (ETH), Solana (SOL), XRP, Cardano (ADA), Dogecoin (DOGE), Avalanche (AVAX), Chainlink (LINK), Polkadot (DOT), Near (NEAR), Litecoin (LTC), Binance Coin (BNB).
   - **Forex (24/5)**: EUR/USD, GBP/USD, USD/JPY, USD/CAD, AUD/USD, USD/CHF, NZD/USD, EUR/GBP, EUR/JPY, GBP/JPY, AUD/JPY, EUR/CAD.
   - **Commodities & Metals**: Gold (XAU/USD), Silver (XAG/USD), Crude Oil (WTI / USOIL), Brent Oil (UKOIL), Natural Gas, Copper, Platinum.
   - **Indices**: NASDAQ 100 (US100), S&P 500 (US500), Dow Jones 30 (US30), Russell 2000, DAX 40 (GER40), FTSE 100, Nikkei 225.
   - **Top Market Movers**: NVDA, TSLA, MSFT, AAPL, AMZN, GOOGL, META, AMD.

2. **Dual Viewing Modes**:
   - **Option A: Top 10 View (Compact)** — High-priority setup focus.
   - **Option B: Top 30 View (Full)** — Comprehensive cross-market intelligence.
   - Switchable with one click in both the terminal and web interface!

3. **Funding Pips Risk Management Enforced**:
   - Starting Balance: **$5,000.00**
   - Position Sizing: **1.0% ($50) to 2.0% ($100)** risk per trade.
   - Max Daily Drawdown: **5.0% ($250.00)** strict circuit breaker.
   - Max Total Drawdown: **10.0% ($500.00)** challenge limit.
   - Max Correlated Open Positions: **3**.
   - Built-in **Match-Trader Lot Size Calculator** for every single trade setup!

4. **Lightning-Fast Architecture**:
   - Parallel multi-threaded data engine fetches 46 assets in ~2 seconds.
   - In-memory cache eliminates rate limits.
   - Never freezes, drops, or fails on any symbol.

---

## 🖥️ Local Usage (Windows)

Launch directly from your desktop using the convenient shortcuts:
- **`Launch_Top_30_Signals.bat`**: Runs the terminal scanner in 30-signal mode.
- **`Launch_Top_10_Signals.bat`**: Runs the terminal scanner in 10-signal mode.
- **`Launch_Web_Signals.bat`**: Starts the local web server and opens http://127.0.0.1:5000 in your browser.

Or run manually via Command Prompt:
```bash
# Run Top 30 Terminal Scanner
python console_scanner.py --top 30

# Run Top 10 Terminal Scanner
python console_scanner.py --top 10

# Run Web Dashboard locally
python app.py
```

---

## ☁️ Deploy Online via GitHub & Render.com

Deploy to Render.com in under 3 minutes for free mobile and remote access:

See detailed guide: [DEPLOYMENT_GUIDE.md](file:///c:/Users/oegar/OneDrive/Documents/Crypto%202026%20-%20Pips,%20Coinbase/DEPLOYMENT_GUIDE.md)

### Quick Deployment Steps:
1. Create a repository on [GitHub](https://github.com/new) named `crypto-trade-signals`.
2. Push with 1-Click:
   - Double-click **`Push_To_GitHub.bat`** on your **Desktop** (or in this folder).
   - Or run in terminal:
     ```bash
     git remote add origin https://github.com/omareg03/crypto-trade-signals.git
     git branch -M main
     git push -u origin main
     ```
3. On [Render.com](https://render.com), click **New +** -> **Web Service** -> select your repository.
4. Settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --workers 1 --threads 4 --timeout 120`
5. Render generates a public URL (e.g. `https://crypto-trade-signals.onrender.com`).
6. Bookmark on your iPhone or Android phone ("Add to Home Screen") to access from work or on the go!
