# Cloudflare Worker Reverse Proxy Setup Guide

This lightweight worker acts as a secure, transparent reverse proxy between Render and CoinSwitch Pro.

### Why It's Needed:
Render uses shared datacenter IP subnets that crypto exchanges sometimes rate-limit or flag. Cloudflare Workers route our requests through clean, trusted edge nodes located across India and Asia.

### Step-by-Step Deployment (Takes 2 Minutes):
1. Log in to [dash.cloudflare.com](https://dash.cloudflare.com/).
2. On the left sidebar, click **Compute (Workers & Pages)**.
3. Click the blue button **Create application** -> **Create Worker**.
4. Give it a name, e.g.: `coinswitch-proxy`.
5. Click **Deploy**.
6. On the next screen, click **Edit code**.
7. Delete any default code in `worker.js`, copy everything from `worker.js` in this folder, and paste it in.
8. Click **Deploy** in the top-right corner.
9. Copy your new Worker URL (e.g. `https://coinswitch-proxy.yourname.workers.dev`).
10. Put this URL in your `.env` or Render environment variables under `COINSWITCH_PROXY_URL`.
