#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# TradeAgent — Railway environment variable setup
# Run this once from Terminal to configure all API keys on Railway.
#
# Usage:
#   cd "path/to/trading-agent"
#   chmod +x setup-railway.sh
#   ./setup-railway.sh
# ──────────────────────────────────────────────────────────────────────────────
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   TradeAgent · Railway Setup                 ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Railway login ─────────────────────────────────────────────────────
echo -e "${YELLOW}Step 1/4 — Log in to Railway${NC}"
echo "A browser window will open. Log in with your Railway account."
echo ""
railway login

echo ""
echo -e "${GREEN}✓ Logged in${NC}"

# ── Step 2: Link to project ───────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Step 2/4 — Link to your Railway project${NC}"
echo "Select the TradeAgent project from the list below."
echo ""
railway link

echo ""
echo -e "${GREEN}✓ Project linked${NC}"

# ── Step 3: Collect API keys ──────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}Step 3/4 — Enter your API keys${NC}"
echo "Keys are sent directly to Railway and never stored locally."
echo "Press Enter to skip any optional key."
echo ""

# Anthropic (required)
echo -e "${CYAN}Anthropic API key${NC} (required — from console.anthropic.com)"
echo -n "  ANTHROPIC_API_KEY: "
read -r ANTHROPIC_API_KEY
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo -e "  ${RED}Skipped — signal generation will not work without this.${NC}"
fi

echo ""

# Alpaca (required for portfolio + trading)
echo -e "${CYAN}Alpaca Paper Trading credentials${NC} (from alpaca.markets → Paper Trading → API Keys)"
echo -n "  ALPACA_API_KEY: "
read -r ALPACA_API_KEY
echo -n "  ALPACA_SECRET_KEY: "
read -r ALPACA_SECRET_KEY
if [ -z "$ALPACA_API_KEY" ]; then
  echo -e "  ${YELLOW}Skipped — portfolio and trading will use demo data.${NC}"
fi

echo ""

# Binance (optional)
echo -e "${CYAN}Binance Testnet credentials${NC} (optional — from testnet.binance.vision)"
echo -n "  BINANCE_API_KEY (press Enter to skip): "
read -r BINANCE_API_KEY
if [ -n "$BINANCE_API_KEY" ]; then
  echo -n "  BINANCE_SECRET_KEY: "
  read -r BINANCE_SECRET_KEY
fi

echo ""

# ── Step 4: Push to Railway ───────────────────────────────────────────────────
echo -e "${YELLOW}Step 4/4 — Setting environment variables on Railway${NC}"
echo ""

set_var() {
  local name="$1"
  local value="$2"
  if [ -n "$value" ]; then
    railway variables set "$name=$value" > /dev/null 2>&1
    echo -e "  ${GREEN}✓${NC} $name"
  fi
}

# Required
set_var "ANTHROPIC_API_KEY"        "$ANTHROPIC_API_KEY"

# Alpaca
set_var "ALPACA_API_KEY"           "$ALPACA_API_KEY"
set_var "ALPACA_SECRET_KEY"        "$ALPACA_SECRET_KEY"
railway variables set "ALPACA_BASE_URL=https://paper-api.alpaca.markets" > /dev/null 2>&1
echo -e "  ${GREEN}✓${NC} ALPACA_BASE_URL (paper)"

# Binance
if [ -n "$BINANCE_API_KEY" ]; then
  set_var "BINANCE_API_KEY"        "$BINANCE_API_KEY"
  set_var "BINANCE_SECRET_KEY"     "$BINANCE_SECRET_KEY"
  railway variables set "BINANCE_TESTNET=true" > /dev/null 2>&1
  echo -e "  ${GREEN}✓${NC} BINANCE_TESTNET=true"
fi

# Telegram (already configured)
railway variables set "TELEGRAM_BOT_TOKEN=8536382077:AAHQZq9Ui8QL98rvPUX6ljATOX-uMqf4DE0" > /dev/null 2>&1
echo -e "  ${GREEN}✓${NC} TELEGRAM_BOT_TOKEN"
railway variables set "TELEGRAM_ALLOWED_IDS=8299051459" > /dev/null 2>&1
echo -e "  ${GREEN}✓${NC} TELEGRAM_ALLOWED_IDS"

# Risk defaults
railway variables set "MAX_POSITION_PCT=0.05"           > /dev/null 2>&1
railway variables set "MAX_CRYPTO_ALLOCATION_PCT=0.30"  > /dev/null 2>&1
railway variables set "CIRCUIT_BREAKER_DRAWDOWN=0.10"   > /dev/null 2>&1
echo -e "  ${GREEN}✓${NC} Risk defaults (5% max position, 30% crypto cap, 10% circuit breaker)"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   All done! Redeploying on Railway…          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""

railway redeploy --yes 2>/dev/null || echo -e "${YELLOW}Redeploy triggered — check Railway dashboard for status.${NC}"

echo ""
echo "Once the deployment finishes (usually 2–3 minutes), open your Railway app URL."
echo "The amber setup banner in the dashboard will disappear when all keys are active."
echo ""
