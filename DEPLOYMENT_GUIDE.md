# 📱 Step-by-Step Render.com & Mobile Deployment Guide

This guide walks you through connecting your GitHub repository to **Render.com** to run your trading scanner online 24/7 for free, allowing you to access live trade signals from your smartphone or work computer.

---

## 🛠️ Step 1: Push this Project to Your GitHub Account

1. Open your browser and go to: **[https://github.com/new](https://github.com/new)**
   *(Log in with your GitHub account: `omareg03`)*
2. In the **Repository name** field, type:
   ```text
   crypto-trade-signals
   ```
3. Set the repository visibility to **Public** (or **Private**).
4. Leave all other options unchecked (*Do NOT initialize with a README, .gitignore, or license*).
5. Click **Create repository**.
6. **Push with 1-Click**:
   - Double-click **`Push_To_GitHub.bat`** on your **Desktop** (or in this folder).
   - Press **Enter** to accept the default repository URL (`https://github.com/omareg03/crypto-trade-signals.git`).
   - The script automatically configures the remote and pushes your code to GitHub!

   *(Alternatively, run these commands in PowerShell or CMD):*
   ```powershell
   cd "C:\Users\oegar\OneDrive\Documents\Crypto 2026 - Pips, Coinbase"
   git remote add origin https://github.com/omareg03/crypto-trade-signals.git
   git branch -M main
   git push -u origin main
   ```

---

## 🌐 Step 2: Deploy Free Web Service on Render.com

1. Go to **[https://render.com](https://render.com)**.
2. Click **Get Started** or **Log In**, and choose **Continue with GitHub**.
3. Once logged into the Render dashboard, click the blue **New +** button in the top navigation bar and select **Web Service**.
4. Choose **Build and deploy from a Git repository** and click **Next**.
5. Connect your GitHub account and find `crypto-trade-signals` in your repository list. Click **Connect**.
6. Configure the deployment settings:
   - **Name**: `quantum-trader-signals` (or any name you like)
   - **Region**: Choose closest to you (e.g. `Ohio (US East)`)
   - **Branch**: `main`
   - **Root Directory**: *(leave blank)*
   - **Runtime**: `Python 3`
   - **Build Command**: 
     ```text
     pip install -r requirements.txt
     ```
   - **Start Command**:
     ```text
     gunicorn app:app --workers 1 --threads 4 --timeout 120
     ```
   - **Instance Type**: Select **Free** ($0 / month)
7. Click **Deploy Web Service** at the bottom.
8. Render will build the container, install packages, and deploy. In about 1 to 2 minutes, the status will show **Live** in green.
9. Render will give you a public URL at the top of the page, for example:
   ```text
   https://quantum-trader-signals.onrender.com
   ```

---

## 📲 Step 3: Access Signals on Mobile Device (Work / On the Go)

1. Open the Render URL on your iPhone (Safari) or Android (Chrome).
2. **Add to Home Screen (Mobile App Experience)**:
   - **iPhone (Safari)**: Tap the **Share** button (box with upward arrow) at the bottom -> Tap **Add to Home Screen** -> Name it "Quantum Signals" -> Tap **Add**.
   - **Android (Chrome)**: Tap the three dots (menu) in the top-right -> Tap **Add to Home screen** (or **Install app**).
3. Now you have an app icon on your phone! Tap it anytime to:
   - View Top 10 or Top 30 signals.
   - Filter by Crypto, Forex, Commodities, Indices, or Stocks.
   - Tap **Calc Lot** on any signal to instantly calculate your lot size for Funding Pips on Match-Trader.
   - Signals refresh automatically every 60 seconds.

---

## ❓ Frequently Asked Questions

### Why did row #10 or certain symbols fail to refresh previously?
In the earlier version:
1. The script requested data serially with a 2.5-second pause per item, which took over 100 seconds per scan. When APIs rate-limited, requests timed out or returned empty values, causing later rows (like #10) to drop or freeze.
2. US equities (like AAPL) close at 4:00 PM EST and don't tick overnight or on weekends.
3. In this updated system, multi-threaded parallel fetching fetches all 46 assets in 2 seconds, memory-caches them safely, and provides instant fallbacks so no symbol ever stalls.

### Can I run both the CMD and the Web App locally?
Yes!
- Double click **`Launch_Top_30_Signals.bat`** on your desktop to run the CMD terminal.
- Double click **`Launch_Web_Signals.bat`** on your desktop to run the local web app on your home network.
- Your original QuantumTrader folder was left completely untouched.
