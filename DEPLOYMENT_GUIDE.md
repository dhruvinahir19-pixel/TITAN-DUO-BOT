# TITAN DUO v4.0 APEX - 24/7 PRODUCTION DEPLOYMENT GUIDE

Follow this step-by-step guide to deploy your bot on **Render.com's Singapore datacenter** and keep it running 24/7/365 at ₹0 cost.

---

## Step 1: Deploy to Render.com (Takes 3 Minutes)

1. Log in to [Render.com](https://dashboard.render.com/) (Sign in with your GitHub account).
2. Click the blue button: **New +** (top-right) $\to$ select **Web Service**.
3. Under "Connect a repository", search for: **`TITAN-DUO-BOT`** and click **Connect**.
4. Configure the settings:
   - **Name**: `titan-duo-bot`
   - **Region**: Select **`Singapore (Southeast Asia)`** *(Lowest latency to CoinSwitch & Neon)*
   - **Branch**: `main`
   - **Runtime**: **`Docker`**
   - **Instance Type**: **`Free`**
5. Scroll down to the **Environment Variables** section and click **Add Environment Variable** to add each of these:

| Key | Value | Note |
| :--- | :--- | :--- |
| `DATABASE_URL` | `postgresql://user:password@ep-xyz.ap-southeast-1.aws.neon.tech/neondb?sslmode=require` | Your Neon Postgres Pooled URL |
| `COINSWITCH_API_KEY` | `your_coinswitch_public_key_hex` | Derived Ed25519 Public Key |
| `COINSWITCH_SECRET_KEY` | `your_coinswitch_secret_key_hex` | 32-Byte Secret Key |
| `COINSWITCH_PROXY_URL` | `https://your-worker.your-subdomain.workers.dev/` | Cloudflare Worker Proxy |
| `TELEGRAM_BOT_TOKEN` | `your_telegram_bot_token` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | `your_telegram_chat_id` | Your Telegram Chat ID |
| `ADMIN_PASSWORD` | `your_dashboard_password` | Web Dashboard Admin Password |
| `EXECUTION_MODE` | `PAPER` | Default: Paper Trading (Zero risk) |
| `BASE_RISK_PCT` | `0.03` | Apex Tier: 3.0% Risk per trade |
| `PORT` | `8000` | Web Dashboard Port |

6. Click the blue button: **Deploy Web Service**.
7. Wait 2 minutes while Render builds the Docker container. Once it says **"Live"**, copy your public URL (e.g. `https://titan-duo-bot.onrender.com`).

---

## Step 2: Configure 24/7 Keep-Alive on cron-job.org (Takes 1 Minute)

Render's free tier spins down if it receives no inbound traffic for 15 minutes. We prevent this permanently by having `cron-job.org` send a ping every 9 minutes:

1. Go to [cron-job.org](https://cron-job.org/) and create a free account (or log in).
2. Click **Create Cronjob** (top-right).
3. Fill in the details:
   - **Title**: `Titan Duo Keep-Alive`
   - **URL**: `https://your-bot-name.onrender.com/ping` *(Replace with your actual Render URL)*
   - **Execution Schedule**: Select **`User-defined`** $\to$ set interval to **`Every 9 minutes`**
4. Click **Save**.
5. **Result**: `cron-job.org` will now ping your bot every 9 minutes 24 hours a day. Your bot will **never sleep**, running continuously at ₹0 cost!

---

## Step 3: Accessing Your Web Dashboard

Once deployed on Render, your web dashboard is accessible from any browser:

🔗 **URL**: `https://your-bot-name.onrender.com/`

Features:
- Live Total Equity in USD ($) and Indian Rupees (₹)
- Real-time active trade status, entry, stop loss, and breakeven indicator
- Closed trades history table
- One-click Emergency Panic button

---

## Step 4: Switching from PAPER to LIVE Trading (When Ready)

Whenever you decide to fund your CoinSwitch Pro account with your capital and want the bot to execute real orders:

1. Go to your [Render Dashboard](https://dashboard.render.com/).
2. Click on **`titan-duo-bot`** $\to$ click on **`Environment`** in the left sidebar.
3. Find **`EXECUTION_MODE`** $\to$ change its value from **`PAPER`** to **`LIVE`**.
4. Click **Save Changes**.
5. Render will automatically reboot the bot in 30 seconds with **LIVE REAL MONEY EXECUTION** activated!
