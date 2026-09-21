/**
 * TITAN DUO v4.0 APEX - CLOUDFLARE WORKER REVERSE PROXY
 * ======================================================
 * Transparent, zero-logging pass-through reverse proxy.
 * Routes API requests from Render through Cloudflare's clean edge network
 * directly to CoinSwitch Pro matching engine (https://api-trading.coinswitch.co).
 * 
 * Free Tier Quota: 100,000 requests/day (Bot uses ~1,500/day = 1.5%)
 */

export default {
  async fetch(request, env, ctx) {
    // Handle CORS pre-flight requests if called from web browser
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
          "Access-Control-Allow-Headers": "*",
        },
      });
    }

    try {
      const incomingUrl = new URL(request.url);
      const targetBase = "https://api-trading.coinswitch.co";
      const targetUrl = `${targetBase}${incomingUrl.pathname}${incomingUrl.search}`;

      // Clone original headers (including Ed25519 signature headers)
      const newHeaders = new Headers(request.headers);
      newHeaders.set("Host", "api-trading.coinswitch.co");

      // Pass through the exact request
      const proxyRequest = new Request(targetUrl, {
        method: request.method,
        headers: newHeaders,
        body: (request.method !== "GET" && request.method !== "HEAD") ? request.body : null,
        redirect: "follow",
      });

      const response = await fetch(proxyRequest);

      // Return exact exchange response with CORS headers
      const responseHeaders = new Headers(response.headers);
      responseHeaders.set("Access-Control-Allow-Origin", "*");

      return new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      });
    } catch (err) {
      return new Response(
        JSON.stringify({
          success: false,
          error: "Cloudflare Reverse Proxy Error",
          message: err.message,
        }),
        {
          status: 502,
          headers: {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
          },
        }
      );
    }
  },
};
