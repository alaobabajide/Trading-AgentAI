import { useState } from "react";
import { BarChart3, Brain, ChevronRight, Loader2, Send } from "lucide-react";
import clsx from "clsx";
import { TradingViewMiniChart } from "../components/TradingViewMiniChart";
import { SignalCard } from "../components/SignalCard";
import { apiHeaders } from "../lib/api";
import type { Signal } from "../lib/types";
import type { TvSymbol } from "../lib/tradingview";

// ── Index catalogue ────────────────────────────────────────────────────────────

interface IndexEntry {
  name: string;
  tv_symbol: string;
  etf_proxy: string;
  description: string;
}

interface IndexGroup {
  id: string;
  label: string;
  color: string;
  entries: IndexEntry[];
}

// TradingView MiniChart widget cannot embed pure index/futures symbols (TVC:, CBOE:, NYMEX:, NSE:).
// All tv_symbol values use embeddable ETF exchange:ticker that tracks the underlying index.
const INDEX_GROUPS: IndexGroup[] = [
  {
    id: "us_broad",
    label: "US Broad Market",
    color: "text-brand-400 bg-brand-500/10 border-brand-500/20",
    entries: [
      // ── S&P 500 ───────────────────────────────────────────────────────────────
      { name: "S&P 500 (SPY)",       tv_symbol: "AMEX:SPY",     etf_proxy: "SPY",   description: "SPDR S&P 500 — largest, most liquid S&P 500 ETF" },
      { name: "S&P 500 (IVV)",       tv_symbol: "AMEX:IVV",     etf_proxy: "IVV",   description: "iShares Core S&P 500 — lowest cost iShares option" },
      { name: "S&P 500 (VOO)",       tv_symbol: "AMEX:VOO",     etf_proxy: "VOO",   description: "Vanguard S&P 500 ETF — ultra-low expense ratio" },
      { name: "S&P 500 (SPLG)",      tv_symbol: "AMEX:SPLG",    etf_proxy: "SPLG",  description: "SPDR Portfolio S&P 500 — cheapest SPY alternative" },
      { name: "S&P 500 Equal Wt",    tv_symbol: "AMEX:RSP",     etf_proxy: "RSP",   description: "Invesco Equal Weight S&P 500 — reduces mega-cap bias" },
      { name: "S&P 500 Growth",      tv_symbol: "AMEX:IVW",     etf_proxy: "IVW",   description: "iShares S&P 500 Growth — high P/E, high momentum" },
      { name: "S&P 500 Value",       tv_symbol: "AMEX:IVE",     etf_proxy: "IVE",   description: "iShares S&P 500 Value — low P/B, low P/E stocks" },
      // ── NASDAQ ────────────────────────────────────────────────────────────────
      { name: "NASDAQ 100 (QQQ)",    tv_symbol: "NASDAQ:QQQ",   etf_proxy: "QQQ",   description: "Invesco QQQ — 100 largest non-financial NASDAQ companies" },
      { name: "NASDAQ 100 (QQQM)",   tv_symbol: "NASDAQ:QQQM",  etf_proxy: "QQQM",  description: "Invesco QQQM — lower-cost version of QQQ" },
      { name: "NASDAQ Composite",    tv_symbol: "NASDAQ:ONEQ",  etf_proxy: "ONEQ",  description: "Fidelity NASDAQ Composite Index ETF — 3000+ stocks" },
      // ── Dow Jones ─────────────────────────────────────────────────────────────
      { name: "Dow Jones (DIA)",     tv_symbol: "AMEX:DIA",     etf_proxy: "DIA",   description: "SPDR Dow Jones Industrial Average — 30 blue chips" },
      // ── Russell ───────────────────────────────────────────────────────────────
      { name: "Russell 1000",        tv_symbol: "AMEX:IWB",     etf_proxy: "IWB",   description: "iShares Russell 1000 — 1000 largest US companies" },
      { name: "Russell 1000 Growth", tv_symbol: "AMEX:IWF",     etf_proxy: "IWF",   description: "iShares Russell 1000 Growth Factor ETF" },
      { name: "Russell 1000 Value",  tv_symbol: "AMEX:IWD",     etf_proxy: "IWD",   description: "iShares Russell 1000 Value Factor ETF" },
      { name: "Russell 2000 (IWM)",  tv_symbol: "AMEX:IWM",     etf_proxy: "IWM",   description: "iShares Russell 2000 — 2000 small-cap US companies" },
      { name: "Russell 2000 (VTWO)", tv_symbol: "AMEX:VTWO",    etf_proxy: "VTWO",  description: "Vanguard Russell 2000 ETF — small-cap alternative" },
      // ── Total Market ──────────────────────────────────────────────────────────
      { name: "Total US Mkt (VTI)",  tv_symbol: "AMEX:VTI",     etf_proxy: "VTI",   description: "Vanguard Total Stock Market — entire US equity market" },
      { name: "Total US Mkt (ITOT)", tv_symbol: "AMEX:ITOT",    etf_proxy: "ITOT",  description: "iShares Core S&P Total US Stock Market ETF" },
      { name: "Total US Mkt (SCHB)", tv_symbol: "AMEX:SCHB",    etf_proxy: "SCHB",  description: "Schwab US Broad Market ETF — 2500+ US stocks" },
      { name: "Extended Market",     tv_symbol: "AMEX:VXF",     etf_proxy: "VXF",   description: "Vanguard Extended Market — mid/small/micro ex S&P 500" },
      // ── Mid & Small Cap ───────────────────────────────────────────────────────
      { name: "S&P MidCap 400 (MDY)",tv_symbol: "AMEX:MDY",     etf_proxy: "MDY",   description: "SPDR S&P MidCap 400 — mid-cap US companies" },
      { name: "S&P MidCap 400 (IJH)",tv_symbol: "AMEX:IJH",     etf_proxy: "IJH",   description: "iShares Core S&P Mid-Cap ETF" },
      { name: "S&P SmallCap 600",    tv_symbol: "AMEX:IJR",     etf_proxy: "IJR",   description: "iShares Core S&P Small-Cap ETF — quality screen" },
      // ── Global ────────────────────────────────────────────────────────────────
      { name: "Total World (VT)",    tv_symbol: "AMEX:VT",      etf_proxy: "VT",    description: "Vanguard Total World — US + all international equities" },
    ],
  },
  {
    id: "us_sectors",
    label: "US Sectors",
    color: "text-violet-400 bg-violet-500/10 border-violet-500/20",
    entries: [
      // ── SPDR Sector ETFs (S&P 500 sectors) ───────────────────────────────────
      { name: "Technology (XLK)",    tv_symbol: "AMEX:XLK",     etf_proxy: "XLK",   description: "SPDR Technology Select — S&P 500 tech sector" },
      { name: "Financials (XLF)",    tv_symbol: "AMEX:XLF",     etf_proxy: "XLF",   description: "SPDR Financial Select — banks, insurers, asset managers" },
      { name: "Healthcare (XLV)",    tv_symbol: "AMEX:XLV",     etf_proxy: "XLV",   description: "SPDR Health Care Select — pharma, biotech, devices" },
      { name: "Energy (XLE)",        tv_symbol: "AMEX:XLE",     etf_proxy: "XLE",   description: "SPDR Energy Select — oil majors & drillers" },
      { name: "Industrials (XLI)",   tv_symbol: "AMEX:XLI",     etf_proxy: "XLI",   description: "SPDR Industrial Select — aerospace, transport, machinery" },
      { name: "Consumer Discr (XLY)",tv_symbol: "AMEX:XLY",     etf_proxy: "XLY",   description: "SPDR Consumer Discretionary — retail, autos, luxury" },
      { name: "Consumer Stpls (XLP)",tv_symbol: "AMEX:XLP",     etf_proxy: "XLP",   description: "SPDR Consumer Staples — food, beverage, household" },
      { name: "Utilities (XLU)",     tv_symbol: "AMEX:XLU",     etf_proxy: "XLU",   description: "SPDR Utilities Select — electric, gas, water utilities" },
      { name: "Real Estate (XLRE)",  tv_symbol: "AMEX:XLRE",    etf_proxy: "XLRE",  description: "SPDR Real Estate Select — REITs & real estate firms" },
      { name: "Materials (XLB)",     tv_symbol: "AMEX:XLB",     etf_proxy: "XLB",   description: "SPDR Materials Select — chemicals, metals, forestry" },
      { name: "Comm Services (XLC)", tv_symbol: "AMEX:XLC",     etf_proxy: "XLC",   description: "SPDR Comm Services Select — media, telecom, internet" },
      // ── Vanguard Sector ETFs ──────────────────────────────────────────────────
      { name: "Technology (VGT)",    tv_symbol: "AMEX:VGT",     etf_proxy: "VGT",   description: "Vanguard Information Technology ETF" },
      { name: "Financials (VFH)",    tv_symbol: "AMEX:VFH",     etf_proxy: "VFH",   description: "Vanguard Financials ETF" },
      { name: "Healthcare (VHT)",    tv_symbol: "AMEX:VHT",     etf_proxy: "VHT",   description: "Vanguard Health Care ETF" },
      { name: "Energy (VDE)",        tv_symbol: "AMEX:VDE",     etf_proxy: "VDE",   description: "Vanguard Energy ETF" },
      { name: "Utilities (VPU)",     tv_symbol: "AMEX:VPU",     etf_proxy: "VPU",   description: "Vanguard Utilities ETF" },
      { name: "Industrials (VIS)",   tv_symbol: "AMEX:VIS",     etf_proxy: "VIS",   description: "Vanguard Industrials ETF" },
      { name: "Real Estate (VNQ)",   tv_symbol: "AMEX:VNQ",     etf_proxy: "VNQ",   description: "Vanguard Real Estate ETF — largest REIT ETF" },
      { name: "Materials (VAW)",     tv_symbol: "AMEX:VAW",     etf_proxy: "VAW",   description: "Vanguard Materials ETF" },
      { name: "Comm Services (VOX)", tv_symbol: "AMEX:VOX",     etf_proxy: "VOX",   description: "Vanguard Communication Services ETF" },
      { name: "Consumer Discr (VCR)",tv_symbol: "AMEX:VCR",     etf_proxy: "VCR",   description: "Vanguard Consumer Discretionary ETF" },
      { name: "Consumer Stpls (VDC)",tv_symbol: "AMEX:VDC",     etf_proxy: "VDC",   description: "Vanguard Consumer Staples ETF" },
      // ── Semiconductors ────────────────────────────────────────────────────────
      { name: "Semis (SOXX)",        tv_symbol: "NASDAQ:SOXX",  etf_proxy: "SOXX",  description: "iShares PHLX Semiconductor — Philadelphia Semi Index" },
      { name: "Semis (SMH)",         tv_symbol: "NASDAQ:SMH",   etf_proxy: "SMH",   description: "VanEck Semiconductor ETF — chip makers & equipment" },
    ],
  },
  {
    id: "us_subsectors",
    label: "US Sub-Sectors",
    color: "text-purple-400 bg-purple-500/10 border-purple-500/20",
    entries: [
      // ── Healthcare ────────────────────────────────────────────────────────────
      { name: "Biotech (XBI)",       tv_symbol: "AMEX:XBI",     etf_proxy: "XBI",   description: "SPDR S&P Biotech — equal-weight, high-risk biotech" },
      { name: "Biotech (IBB)",       tv_symbol: "AMEX:IBB",     etf_proxy: "IBB",   description: "iShares Nasdaq Biotech — cap-weighted large biotech" },
      { name: "Pharmaceuticals",     tv_symbol: "AMEX:PJP",     etf_proxy: "PJP",   description: "Invesco Dynamic Pharmaceuticals ETF" },
      // ── Technology ────────────────────────────────────────────────────────────
      { name: "Software (IGV)",      tv_symbol: "NASDAQ:IGV",   etf_proxy: "IGV",   description: "iShares Expanded Tech-Software Sector ETF" },
      { name: "Cloud Computing",     tv_symbol: "NASDAQ:WCLD",  etf_proxy: "WCLD",  description: "WisdomTree Cloud Computing — pure-play SaaS" },
      { name: "AI & Technology",     tv_symbol: "NYSE:AIQ",     etf_proxy: "AIQ",   description: "Global X AI & Technology ETF" },
      { name: "Cybersecurity (CIBR)",tv_symbol: "NASDAQ:CIBR",  etf_proxy: "CIBR",  description: "First Trust Nasdaq Cybersecurity ETF" },
      { name: "Cybersecurity (HACK)",tv_symbol: "NASDAQ:HACK",  etf_proxy: "HACK",  description: "ETFMG Prime Cyber Security ETF" },
      { name: "Robotics & AI (BOTZ)",tv_symbol: "NASDAQ:BOTZ",  etf_proxy: "BOTZ",  description: "Global X Robotics & Artificial Intelligence ETF" },
      { name: "Robotics (ROBO)",     tv_symbol: "NASDAQ:ROBO",  etf_proxy: "ROBO",  description: "ROBO Global Robotics & Automation Index ETF" },
      { name: "FinTech",             tv_symbol: "AMEX:FINX",    etf_proxy: "FINX",  description: "Global X FinTech ETF — payment processors & neobanks" },
      // ── Energy / Industrials ──────────────────────────────────────────────────
      { name: "Oil & Gas E&P (XOP)", tv_symbol: "AMEX:XOP",     etf_proxy: "XOP",   description: "SPDR S&P Oil & Gas Exploration & Production ETF" },
      { name: "Aerospace/Defense",   tv_symbol: "AMEX:ITA",     etf_proxy: "ITA",   description: "iShares US Aerospace & Defense ETF" },
      { name: "Homebuilders (ITB)",  tv_symbol: "AMEX:ITB",     etf_proxy: "ITB",   description: "iShares US Home Construction ETF" },
      { name: "Homebuilders (XHB)",  tv_symbol: "AMEX:XHB",     etf_proxy: "XHB",   description: "SPDR S&P Homebuilders — broader supply chain" },
      // ── Financials ────────────────────────────────────────────────────────────
      { name: "Regional Banks (KRE)",tv_symbol: "AMEX:KRE",     etf_proxy: "KRE",   description: "SPDR S&P Regional Banking ETF — US regional banks" },
      { name: "Regional Banks (IAT)",tv_symbol: "AMEX:IAT",     etf_proxy: "IAT",   description: "iShares US Regional Banks ETF" },
      // ── Consumer ──────────────────────────────────────────────────────────────
      { name: "Retail (XRT)",        tv_symbol: "AMEX:XRT",     etf_proxy: "XRT",   description: "SPDR S&P Retail ETF — equal-weight retailers" },
      { name: "Airlines (JETS)",     tv_symbol: "AMEX:JETS",    etf_proxy: "JETS",  description: "US Global Jets ETF — global airline industry" },
      // ── Materials ─────────────────────────────────────────────────────────────
      { name: "Metals & Mining (XME)",tv_symbol: "AMEX:XME",    etf_proxy: "XME",   description: "SPDR S&P Metals & Mining ETF" },
      { name: "Global Mining (PICK)", tv_symbol: "AMEX:PICK",   etf_proxy: "PICK",  description: "iShares MSCI Global Metals & Mining Producers" },
    ],
  },
  {
    id: "volatility",
    label: "Volatility",
    color: "text-red-400 bg-red-500/10 border-red-500/20",
    entries: [
      { name: "Ultra VIX (UVXY)",    tv_symbol: "AMEX:UVXY",    etf_proxy: "UVXY",  description: "ProShares Ultra VIX — 1.5× short-term VIX futures" },
      { name: "VIX Short-Term (VIXY)",tv_symbol: "AMEX:VIXY",   etf_proxy: "VIXY",  description: "ProShares VIX Short-Term Futures ETF (1×)" },
      { name: "VIX Mid-Term (VIXM)", tv_symbol: "AMEX:VIXM",    etf_proxy: "VIXM",  description: "ProShares VIX Mid-Term Futures (4–7 month)" },
      { name: "VIX Futures (VXX)",   tv_symbol: "AMEX:VXX",     etf_proxy: "VXX",   description: "iPath Series B S&P 500 VIX Short-Term Futures" },
      { name: "Inverse VIX (SVXY)",  tv_symbol: "AMEX:SVXY",    etf_proxy: "SVXY",  description: "ProShares Short VIX — profits when markets calm" },
      { name: "3× NASDAQ Bull",      tv_symbol: "NASDAQ:TQQQ",  etf_proxy: "TQQQ",  description: "ProShares UltraPro QQQ — 3× daily NASDAQ 100" },
      { name: "3× S&P Bull",         tv_symbol: "AMEX:SPXL",    etf_proxy: "SPXL",  description: "Direxion Daily S&P 500 Bull 3× Shares" },
      { name: "3× S&P Bear",         tv_symbol: "AMEX:SPXS",    etf_proxy: "SPXS",  description: "Direxion Daily S&P 500 Bear 3× Shares" },
      { name: "3× NASDAQ Bear",      tv_symbol: "NASDAQ:SQQQ",  etf_proxy: "SQQQ",  description: "ProShares UltraPro Short QQQ — 3× inverse NASDAQ" },
      { name: "3× Semi Bull (SOXL)", tv_symbol: "AMEX:SOXL",    etf_proxy: "SOXL",  description: "Direxion Daily Semiconductor Bull 3× ETF" },
      { name: "3× Semi Bear (SOXS)", tv_symbol: "AMEX:SOXS",    etf_proxy: "SOXS",  description: "Direxion Daily Semiconductor Bear 3× ETF" },
    ],
  },
  {
    id: "fixed_income",
    label: "Fixed Income",
    color: "text-sky-400 bg-sky-500/10 border-sky-500/20",
    entries: [
      // ── US Treasuries ─────────────────────────────────────────────────────────
      { name: "20+ Yr Treasury (TLT)",tv_symbol: "NASDAQ:TLT",  etf_proxy: "TLT",   description: "iShares 20+ Year Treasury Bond ETF" },
      { name: "20+ Yr Tsy (VGLT)",   tv_symbol: "NASDAQ:VGLT",  etf_proxy: "VGLT",  description: "Vanguard Long-Term Treasury ETF" },
      { name: "Extended Duration",    tv_symbol: "AMEX:EDV",     etf_proxy: "EDV",   description: "Vanguard Extended Duration Treasury (25+ yr)" },
      { name: "Zero Coupon (ZROZ)",   tv_symbol: "AMEX:ZROZ",    etf_proxy: "ZROZ",  description: "PIMCO 25+ Year Zero Coupon US Treasury — max duration" },
      { name: "7–10 Yr Tsy (IEF)",   tv_symbol: "NASDAQ:IEF",   etf_proxy: "IEF",   description: "iShares 7–10 Year Treasury Bond ETF" },
      { name: "7–10 Yr Tsy (VGIT)",  tv_symbol: "NASDAQ:VGIT",  etf_proxy: "VGIT",  description: "Vanguard Intermediate-Term Treasury ETF" },
      { name: "3–7 Yr Treasury",      tv_symbol: "NASDAQ:IEI",   etf_proxy: "IEI",   description: "iShares 3–7 Year Treasury Bond ETF" },
      { name: "1–3 Yr Tsy (SHY)",    tv_symbol: "NASDAQ:SHY",   etf_proxy: "SHY",   description: "iShares 1–3 Year Treasury Bond ETF" },
      { name: "1–3 Yr Tsy (VGSH)",   tv_symbol: "NASDAQ:VGSH",  etf_proxy: "VGSH",  description: "Vanguard Short-Term Treasury ETF" },
      { name: "T-Bills (BIL)",        tv_symbol: "AMEX:BIL",     etf_proxy: "BIL",   description: "SPDR Bloomberg 1–3 Month T-Bill ETF — near-zero risk" },
      { name: "Overnight (SGOV)",     tv_symbol: "AMEX:SGOV",    etf_proxy: "SGOV",  description: "iShares 0–3 Month Treasury Bond ETF" },
      // ── Aggregate / Broad ─────────────────────────────────────────────────────
      { name: "US Agg Bond (AGG)",    tv_symbol: "NASDAQ:AGG",   etf_proxy: "AGG",   description: "iShares Core US Aggregate Bond Market" },
      { name: "Total Bond (BND)",     tv_symbol: "NASDAQ:BND",   etf_proxy: "BND",   description: "Vanguard Total Bond Market ETF" },
      { name: "Intl Bond (BNDX)",     tv_symbol: "NASDAQ:BNDX",  etf_proxy: "BNDX",  description: "Vanguard Total International Bond ETF (USD-hedged)" },
      // ── Corporate Bonds ───────────────────────────────────────────────────────
      { name: "Inv-Grade Corp (LQD)", tv_symbol: "NASDAQ:LQD",   etf_proxy: "LQD",   description: "iShares iBoxx Investment Grade Corporate Bond" },
      { name: "Long Corp (VCLT)",     tv_symbol: "NASDAQ:VCLT",  etf_proxy: "VCLT",  description: "Vanguard Long-Term Corporate Bond ETF" },
      { name: "Interm Corp (IGIB)",   tv_symbol: "NASDAQ:IGIB",  etf_proxy: "IGIB",  description: "iShares Intermediate-Term Corporate Bond ETF" },
      { name: "High Yield (HYG)",     tv_symbol: "NASDAQ:HYG",   etf_proxy: "HYG",   description: "iShares iBoxx High Yield Corporate Bond" },
      { name: "High Yield (JNK)",     tv_symbol: "AMEX:JNK",     etf_proxy: "JNK",   description: "SPDR Bloomberg High Yield Bond ETF" },
      { name: "US High Yield (USHY)", tv_symbol: "AMEX:USHY",    etf_proxy: "USHY",  description: "iShares Broad US High Yield Corporate Bond" },
      { name: "Bank Loans (BKLN)",    tv_symbol: "AMEX:BKLN",    etf_proxy: "BKLN",  description: "Invesco Senior Loan ETF — floating-rate senior loans" },
      { name: "Senior Loans (SRLN)", tv_symbol: "AMEX:SRLN",    etf_proxy: "SRLN",  description: "SPDR Blackstone Senior Loan ETF" },
      // ── Inflation-Protected ───────────────────────────────────────────────────
      { name: "TIPS (TIP)",           tv_symbol: "NASDAQ:TIP",   etf_proxy: "TIP",   description: "iShares TIPS Bond — inflation-protected Treasuries" },
      { name: "Short TIPS (VTIP)",    tv_symbol: "NASDAQ:VTIP",  etf_proxy: "VTIP",  description: "Vanguard Short-Term Inflation-Protected Securities" },
      { name: "TIPS (SCHP)",          tv_symbol: "AMEX:SCHP",    etf_proxy: "SCHP",  description: "Schwab US TIPS ETF" },
      // ── Emerging & Muni ───────────────────────────────────────────────────────
      { name: "EM Bonds (EMB)",       tv_symbol: "NASDAQ:EMB",   etf_proxy: "EMB",   description: "iShares J.P. Morgan USD Emerging Markets Bond" },
      { name: "EM Bonds (PCY)",       tv_symbol: "NASDAQ:PCY",   etf_proxy: "PCY",   description: "Invesco Emerging Markets Sovereign Debt ETF" },
      { name: "EM Bonds (VWOB)",      tv_symbol: "NASDAQ:VWOB",  etf_proxy: "VWOB",  description: "Vanguard Emerging Markets Government Bond ETF" },
      { name: "Muni Bonds (MUB)",     tv_symbol: "NASDAQ:MUB",   etf_proxy: "MUB",   description: "iShares National Muni Bond ETF" },
      { name: "Muni Bonds (VTEB)",    tv_symbol: "AMEX:VTEB",    etf_proxy: "VTEB",  description: "Vanguard Tax-Exempt Bond ETF" },
      { name: "HY Muni (HYD)",        tv_symbol: "AMEX:HYD",     etf_proxy: "HYD",   description: "VanEck High Yield Muni ETF" },
    ],
  },
  {
    id: "macro",
    label: "Macro & FX",
    color: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20",
    entries: [
      { name: "US Dollar (UUP)",      tv_symbol: "AMEX:UUP",     etf_proxy: "UUP",   description: "Invesco DB US Dollar Index Bullish Fund — DXY proxy" },
      { name: "Euro (FXE)",           tv_symbol: "AMEX:FXE",     etf_proxy: "FXE",   description: "Invesco CurrencyShares Euro Trust ETF" },
      { name: "Japanese Yen (FXY)",   tv_symbol: "AMEX:FXY",     etf_proxy: "FXY",   description: "Invesco CurrencyShares Japanese Yen Trust" },
      { name: "British Pound (FXB)",  tv_symbol: "AMEX:FXB",     etf_proxy: "FXB",   description: "Invesco CurrencyShares British Pound Sterling Trust" },
      { name: "Swiss Franc (FXF)",    tv_symbol: "AMEX:FXF",     etf_proxy: "FXF",   description: "Invesco CurrencyShares Swiss Franc Trust" },
      { name: "Australian $ (FXA)",   tv_symbol: "AMEX:FXA",     etf_proxy: "FXA",   description: "Invesco CurrencyShares Australian Dollar Trust" },
      { name: "Gold (GLD)",           tv_symbol: "AMEX:GLD",     etf_proxy: "GLD",   description: "SPDR Gold Shares — gold spot price proxy" },
      { name: "Silver (SLV)",         tv_symbol: "AMEX:SLV",     etf_proxy: "SLV",   description: "iShares Silver Trust — silver spot proxy" },
    ],
  },
  {
    id: "factor",
    label: "Factor & Dividend",
    color: "text-teal-400 bg-teal-500/10 border-teal-500/20",
    entries: [
      { name: "Dividend Growth (VIG)",tv_symbol: "NASDAQ:VIG",   etf_proxy: "VIG",   description: "Vanguard Dividend Appreciation — 10+ yr dividend growers" },
      { name: "High Dividend (VYM)", tv_symbol: "AMEX:VYM",     etf_proxy: "VYM",   description: "Vanguard High Dividend Yield ETF" },
      { name: "Dividend (HDV)",       tv_symbol: "AMEX:HDV",     etf_proxy: "HDV",   description: "iShares Core High Dividend ETF" },
      { name: "Div Yield (DVY)",      tv_symbol: "NASDAQ:DVY",   etf_proxy: "DVY",   description: "iShares Select Dividend ETF — high current dividend yield" },
      { name: "Schwab Dividend (SCHD)",tv_symbol: "AMEX:SCHD",   etf_proxy: "SCHD",  description: "Schwab US Dividend Equity — quality + dividend screen" },
      { name: "Div Growth (DGRO)",    tv_symbol: "AMEX:DGRO",    etf_proxy: "DGRO",  description: "iShares Core Dividend Growth ETF" },
      { name: "Div Aristocrats",      tv_symbol: "AMEX:NOBL",    etf_proxy: "NOBL",  description: "ProShares S&P 500 Dividend Aristocrats (25+ yr growers)" },
      { name: "Div Growers (DGRW)",   tv_symbol: "AMEX:DGRW",    etf_proxy: "DGRW",  description: "WisdomTree US Quality Dividend Growth ETF" },
      { name: "Quality (QUAL)",       tv_symbol: "AMEX:QUAL",    etf_proxy: "QUAL",  description: "iShares MSCI USA Quality Factor ETF" },
      { name: "Momentum (MTUM)",      tv_symbol: "AMEX:MTUM",    etf_proxy: "MTUM",  description: "iShares MSCI USA Momentum Factor ETF" },
      { name: "Low Volatility (USMV)",tv_symbol: "AMEX:USMV",    etf_proxy: "USMV",  description: "iShares MSCI USA Min Vol Factor ETF" },
      { name: "Low Vol (SPLV)",       tv_symbol: "AMEX:SPLV",    etf_proxy: "SPLV",  description: "Invesco S&P 500 Low Volatility ETF" },
      { name: "Value (RPV)",          tv_symbol: "AMEX:RPV",     etf_proxy: "RPV",   description: "Invesco S&P 500 Pure Value ETF" },
      { name: "High Beta (SPHB)",     tv_symbol: "AMEX:SPHB",    etf_proxy: "SPHB",  description: "Invesco S&P 500 High Beta ETF" },
      { name: "Cash Cows (COWZ)",     tv_symbol: "AMEX:COWZ",    etf_proxy: "COWZ",  description: "Pacer US Cash Cows 100 — high free cash flow yield" },
      { name: "Small Value (CALF)",   tv_symbol: "AMEX:CALF",    etf_proxy: "CALF",  description: "Pacer US Small Cap Cash Cows 100 ETF" },
    ],
  },
  {
    id: "thematic",
    label: "Thematic & Innovation",
    color: "text-fuchsia-400 bg-fuchsia-500/10 border-fuchsia-500/20",
    entries: [
      // ── ARK Funds ─────────────────────────────────────────────────────────────
      { name: "ARK Innovation (ARKK)",tv_symbol: "AMEX:ARKK",   etf_proxy: "ARKK",  description: "ARK Innovation ETF — disruptive technology companies" },
      { name: "ARK Genomics (ARKG)", tv_symbol: "AMEX:ARKG",    etf_proxy: "ARKG",  description: "ARK Genomic Revolution — biotech & gene editing" },
      { name: "ARK Robotics (ARKQ)", tv_symbol: "AMEX:ARKQ",    etf_proxy: "ARKQ",  description: "ARK Autonomous Technology & Robotics ETF" },
      { name: "ARK FinTech (ARKF)",  tv_symbol: "AMEX:ARKF",    etf_proxy: "ARKF",  description: "ARK Fintech Innovation ETF" },
      { name: "ARK Web 3.0 (ARKW)",  tv_symbol: "AMEX:ARKW",    etf_proxy: "ARKW",  description: "ARK Next Generation Internet ETF" },
      // ── Crypto ETFs ───────────────────────────────────────────────────────────
      { name: "Bitcoin ETF (IBIT)",   tv_symbol: "NASDAQ:IBIT",  etf_proxy: "IBIT",  description: "iShares Bitcoin Trust — largest spot Bitcoin ETF" },
      { name: "Bitcoin ETF (FBTC)",   tv_symbol: "NASDAQ:FBTC",  etf_proxy: "FBTC",  description: "Fidelity Wise Origin Bitcoin Fund" },
      { name: "Bitcoin (GBTC)",       tv_symbol: "AMEX:GBTC",    etf_proxy: "GBTC",  description: "Grayscale Bitcoin Trust ETF" },
      { name: "2× Bitcoin (BITX)",    tv_symbol: "NASDAQ:BITX",  etf_proxy: "BITX",  description: "2× Bitcoin Strategy ETF — leveraged Bitcoin exposure" },
      { name: "Bitcoin Strategy (BITO)",tv_symbol: "AMEX:BITO",  etf_proxy: "BITO",  description: "ProShares Bitcoin Strategy ETF — futures-based" },
      // ── Clean Energy / EV ─────────────────────────────────────────────────────
      { name: "Clean Energy (ICLN)",  tv_symbol: "NASDAQ:ICLN",  etf_proxy: "ICLN",  description: "iShares Global Clean Energy ETF" },
      { name: "Wind Energy (FAN)",    tv_symbol: "AMEX:FAN",     etf_proxy: "FAN",   description: "First Trust Global Wind Energy ETF" },
      { name: "Clean Tech (QCLN)",    tv_symbol: "NASDAQ:QCLN",  etf_proxy: "QCLN",  description: "First Trust NASDAQ Clean Edge Green Energy ETF" },
      { name: "EV & Autonomy (DRIV)", tv_symbol: "AMEX:DRIV",    etf_proxy: "DRIV",  description: "Global X Autonomous & Electric Vehicles ETF" },
      { name: "Lithium & Battery",    tv_symbol: "AMEX:LIT",     etf_proxy: "LIT",   description: "Global X Lithium & Battery Tech ETF" },
      { name: "Battery Tech (BATT)",  tv_symbol: "AMEX:BATT",    etf_proxy: "BATT",  description: "Amplify Lithium & Battery Technology ETF" },
      // ── Blockchain / Digital ──────────────────────────────────────────────────
      { name: "Blockchain (BLOK)",    tv_symbol: "NASDAQ:BLOK",  etf_proxy: "BLOK",  description: "Amplify Transformational Data Sharing ETF" },
      { name: "Metaverse (METV)",     tv_symbol: "AMEX:METV",    etf_proxy: "METV",  description: "Roundhill Ball Metaverse ETF" },
      // ── Infrastructure / Industrial ───────────────────────────────────────────
      { name: "Infrastructure (PAVE)",tv_symbol: "AMEX:PAVE",    etf_proxy: "PAVE",  description: "Global X US Infrastructure Development ETF" },
      { name: "Global Infra (IFRA)",  tv_symbol: "AMEX:IFRA",    etf_proxy: "IFRA",  description: "iShares US Infrastructure ETF" },
      // ── Niche / Emerging ──────────────────────────────────────────────────────
      { name: "Space (UFO)",          tv_symbol: "AMEX:UFO",     etf_proxy: "UFO",   description: "Procure Space ETF — satellite, launch & space tech" },
      { name: "Space (ROKT)",         tv_symbol: "AMEX:ROKT",    etf_proxy: "ROKT",  description: "ARK Space Exploration & Innovation ETF" },
      { name: "Esports / Gaming",     tv_symbol: "AMEX:ESPO",    etf_proxy: "ESPO",  description: "VanEck Video Gaming and eSports ETF" },
      { name: "Esports (NERD)",       tv_symbol: "AMEX:NERD",    etf_proxy: "NERD",  description: "Roundhill BITKRAFT Esports & Digital Entertainment ETF" },
      { name: "Cannabis (MJ)",        tv_symbol: "AMEX:MJ",      etf_proxy: "MJ",    description: "ETFMG Alternative Harvest ETF — global cannabis" },
    ],
  },
  {
    id: "international",
    label: "International",
    color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    entries: [
      // ── Broad International ───────────────────────────────────────────────────
      { name: "Dev. Mkts ex-US (VEA)",tv_symbol: "NASDAQ:VEA",  etf_proxy: "VEA",   description: "Vanguard FTSE Developed ex-US Markets ETF" },
      { name: "Dev. Mkts (EFA)",      tv_symbol: "AMEX:EFA",     etf_proxy: "EFA",   description: "iShares MSCI EAFE — Europe, Australasia, Far East" },
      { name: "All-World ex-US (VEU)",tv_symbol: "AMEX:VEU",    etf_proxy: "VEU",   description: "Vanguard FTSE All-World ex-US ETF" },
      { name: "Emerging Mkts (EEM)",  tv_symbol: "AMEX:EEM",     etf_proxy: "EEM",   description: "iShares MSCI Emerging Markets ETF" },
      { name: "Emerging Mkts (VWO)",  tv_symbol: "AMEX:VWO",     etf_proxy: "VWO",   description: "Vanguard FTSE Emerging Markets ETF" },
      { name: "Emerging Mkts (IEMG)", tv_symbol: "AMEX:IEMG",    etf_proxy: "IEMG",  description: "iShares Core MSCI Emerging Markets ETF" },
      { name: "EM ex-China (EMXC)",   tv_symbol: "NASDAQ:EMXC",  etf_proxy: "EMXC",  description: "iShares MSCI Emerging Markets ex China ETF" },
      // ── Europe ────────────────────────────────────────────────────────────────
      { name: "Euro Stoxx 50 (FEZ)",  tv_symbol: "AMEX:FEZ",     etf_proxy: "FEZ",   description: "SPDR Euro Stoxx 50 — top 50 Eurozone blue-chips" },
      { name: "FTSE 100 UK (EWU)",    tv_symbol: "AMEX:EWU",     etf_proxy: "EWU",   description: "iShares MSCI United Kingdom ETF — FTSE 100 proxy" },
      { name: "DAX 40 Germany (EWG)", tv_symbol: "AMEX:EWG",     etf_proxy: "EWG",   description: "iShares MSCI Germany ETF — DAX 40 proxy" },
      { name: "CAC 40 France (EWQ)",  tv_symbol: "AMEX:EWQ",     etf_proxy: "EWQ",   description: "iShares MSCI France ETF — CAC 40 proxy" },
      { name: "Switzerland (EWL)",    tv_symbol: "AMEX:EWL",     etf_proxy: "EWL",   description: "iShares MSCI Switzerland ETF — SMI proxy" },
      { name: "Sweden (EWD)",         tv_symbol: "AMEX:EWD",     etf_proxy: "EWD",   description: "iShares MSCI Sweden ETF" },
      { name: "Netherlands (EWN)",    tv_symbol: "AMEX:EWN",     etf_proxy: "EWN",   description: "iShares MSCI Netherlands ETF" },
      { name: "Spain (EWP)",          tv_symbol: "AMEX:EWP",     etf_proxy: "EWP",   description: "iShares MSCI Spain ETF — IBEX 35 proxy" },
      { name: "Italy (EWI)",          tv_symbol: "AMEX:EWI",     etf_proxy: "EWI",   description: "iShares MSCI Italy ETF — MIB index proxy" },
      // ── Asia-Pacific ──────────────────────────────────────────────────────────
      { name: "Nikkei 225 (EWJ)",     tv_symbol: "AMEX:EWJ",     etf_proxy: "EWJ",   description: "iShares MSCI Japan ETF — Nikkei 225 proxy" },
      { name: "Hang Seng (EWH)",      tv_symbol: "AMEX:EWH",     etf_proxy: "EWH",   description: "iShares MSCI Hong Kong ETF — Hang Seng proxy" },
      { name: "China Large Cap (MCHI)",tv_symbol: "AMEX:MCHI",   etf_proxy: "MCHI",  description: "iShares MSCI China ETF" },
      { name: "China A-Shares (ASHR)",tv_symbol: "AMEX:ASHR",    etf_proxy: "ASHR",  description: "Xtrackers Harvest CSI 300 China A-Shares ETF" },
      { name: "China Internet (KWEB)",tv_symbol: "AMEX:KWEB",    etf_proxy: "KWEB",  description: "KraneShares CSI China Internet ETF" },
      { name: "India (INDA)",         tv_symbol: "AMEX:INDA",    etf_proxy: "INDA",  description: "iShares MSCI India ETF — Nifty 50 proxy" },
      { name: "Taiwan (EWT)",         tv_symbol: "AMEX:EWT",     etf_proxy: "EWT",   description: "iShares MSCI Taiwan ETF — weighted toward TSM" },
      { name: "South Korea (EWY)",    tv_symbol: "AMEX:EWY",     etf_proxy: "EWY",   description: "iShares MSCI South Korea ETF — KOSPI proxy" },
      { name: "Australia (EWA)",      tv_symbol: "AMEX:EWA",     etf_proxy: "EWA",   description: "iShares MSCI Australia ETF — ASX 200 proxy" },
      { name: "Singapore (EWS)",      tv_symbol: "AMEX:EWS",     etf_proxy: "EWS",   description: "iShares MSCI Singapore ETF — STI proxy" },
      // ── Americas ex-US ────────────────────────────────────────────────────────
      { name: "Brazil (EWZ)",         tv_symbol: "AMEX:EWZ",     etf_proxy: "EWZ",   description: "iShares MSCI Brazil ETF — Bovespa proxy" },
      { name: "Mexico (EWW)",         tv_symbol: "AMEX:EWW",     etf_proxy: "EWW",   description: "iShares MSCI Mexico ETF — IPC index proxy" },
      { name: "Canada (EWC)",         tv_symbol: "AMEX:EWC",     etf_proxy: "EWC",   description: "iShares MSCI Canada ETF — S&P/TSX proxy" },
      { name: "Chile (ECH)",          tv_symbol: "AMEX:ECH",     etf_proxy: "ECH",   description: "iShares MSCI Chile ETF — IPSA index proxy" },
    ],
  },
  {
    id: "commodities",
    label: "Commodities",
    color: "text-orange-400 bg-orange-500/10 border-orange-500/20",
    entries: [
      // ── Precious Metals ───────────────────────────────────────────────────────
      { name: "Gold (GLD)",           tv_symbol: "AMEX:GLD",     etf_proxy: "GLD",   description: "SPDR Gold Shares — gold spot price proxy" },
      { name: "Gold (IAU)",           tv_symbol: "AMEX:IAU",     etf_proxy: "IAU",   description: "iShares Gold Trust — lower cost gold alternative" },
      { name: "Gold (GLDM)",          tv_symbol: "AMEX:GLDM",    etf_proxy: "GLDM",  description: "SPDR Gold MiniShares — cheapest physical gold ETF" },
      { name: "Gold (SGOL)",          tv_symbol: "AMEX:SGOL",    etf_proxy: "SGOL",  description: "Aberdeen Physical Gold Shares ETF" },
      { name: "Silver (SLV)",         tv_symbol: "AMEX:SLV",     etf_proxy: "SLV",   description: "iShares Silver Trust — silver spot proxy" },
      { name: "Silver (SIVR)",        tv_symbol: "AMEX:SIVR",    etf_proxy: "SIVR",  description: "Aberdeen Physical Silver Shares ETF" },
      { name: "Platinum (PPLT)",      tv_symbol: "AMEX:PPLT",    etf_proxy: "PPLT",  description: "Aberdeen Physical Platinum Shares ETF" },
      // ── Gold & Silver Miners ──────────────────────────────────────────────────
      { name: "Gold Miners (GDX)",    tv_symbol: "AMEX:GDX",     etf_proxy: "GDX",   description: "VanEck Gold Miners ETF — senior gold producers" },
      { name: "Jr Gold Miners (GDXJ)",tv_symbol: "AMEX:GDXJ",    etf_proxy: "GDXJ",  description: "VanEck Junior Gold Miners — higher-risk/reward" },
      { name: "Silver Miners (SIL)",  tv_symbol: "AMEX:SIL",     etf_proxy: "SIL",   description: "Global X Silver Miners ETF" },
      // ── Energy ────────────────────────────────────────────────────────────────
      { name: "Crude Oil (USO)",      tv_symbol: "AMEX:USO",     etf_proxy: "USO",   description: "United States Oil Fund — WTI crude oil proxy" },
      { name: "Oil Fund (DBO)",       tv_symbol: "AMEX:DBO",     etf_proxy: "DBO",   description: "Invesco DB Oil Fund — optimized crude exposure" },
      { name: "Natural Gas (UNG)",    tv_symbol: "AMEX:UNG",     etf_proxy: "UNG",   description: "United States Natural Gas Fund" },
      { name: "Nat Gas 2× (BOIL)",    tv_symbol: "AMEX:BOIL",    etf_proxy: "BOIL",  description: "ProShares Ultra Bloomberg Natural Gas (2×)" },
      // ── Nuclear / Metals ──────────────────────────────────────────────────────
      { name: "Uranium (URA)",        tv_symbol: "AMEX:URA",     etf_proxy: "URA",   description: "Global X Uranium ETF — nuclear fuel cycle" },
      { name: "Uranium Miners (URNM)",tv_symbol: "AMEX:URNM",    etf_proxy: "URNM",  description: "Sprott Uranium Miners ETF — uranium mining companies" },
      { name: "Copper (CPER)",        tv_symbol: "AMEX:CPER",    etf_proxy: "CPER",  description: "United States Copper Index Fund" },
      // ── Agriculture ───────────────────────────────────────────────────────────
      { name: "Agriculture (DBA)",    tv_symbol: "AMEX:DBA",     etf_proxy: "DBA",   description: "Invesco DB Agriculture Fund — grains, softs, livestock" },
      { name: "Corn (CORN)",          tv_symbol: "AMEX:CORN",    etf_proxy: "CORN",  description: "Teucrium Corn Fund — corn futures ETF" },
      { name: "Wheat (WEAT)",         tv_symbol: "AMEX:WEAT",    etf_proxy: "WEAT",  description: "Teucrium Wheat Fund — wheat futures ETF" },
      { name: "Soybeans (SOYB)",      tv_symbol: "AMEX:SOYB",    etf_proxy: "SOYB",  description: "Teucrium Soybean Fund — soybean futures ETF" },
      { name: "Agribusiness (MOO)",   tv_symbol: "AMEX:MOO",     etf_proxy: "MOO",   description: "VanEck Agribusiness ETF — global food supply chain" },
      // ── Broad Commodities ─────────────────────────────────────────────────────
      { name: "Broad Cmdty (PDBC)",   tv_symbol: "AMEX:PDBC",    etf_proxy: "PDBC",  description: "Invesco Optimum Yield Diversified Commodity" },
      { name: "Broad Cmdty (DJP)",    tv_symbol: "AMEX:DJP",     etf_proxy: "DJP",   description: "iPath Bloomberg Commodity Index Total Return" },
      { name: "Broad Cmdty (GSG)",    tv_symbol: "AMEX:GSG",     etf_proxy: "GSG",   description: "iShares S&P GSCI Commodity-Indexed Trust" },
    ],
  },
];

// ── Signal runner ──────────────────────────────────────────────────────────────

interface SignalState {
  symbol: string;
  loading: boolean;
  signal: Signal | null;
  error: string | null;
}

async function runSignal(etfProxy: string, paperMode: boolean): Promise<Signal> {
  const resp = await fetch("/api/signal", {
    method: "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ symbol: etfProxy, asset_class: "stock", paper_mode: paperMode }),
    signal: AbortSignal.timeout(120_000),
  });
  const text = await resp.text();
  if (!text) throw new Error(`HTTP ${resp.status}`);
  const data = JSON.parse(text);
  if (!resp.ok) throw new Error(data?.detail ?? `HTTP ${resp.status}`);
  return data as Signal;
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function IndexCard({
  entry,
  signalState,
  onAnalyse,
}: {
  entry: IndexEntry;
  signalState: SignalState | undefined;
  onAnalyse: (entry: IndexEntry) => void;
}) {
  const sym: TvSymbol = {
    tv: entry.tv_symbol,
    label: entry.name,
    group: "Indices",
    description: entry.description,
  };

  const isLoading = signalState?.symbol === entry.etf_proxy && signalState.loading;

  return (
    <div className="glass rounded-2xl overflow-hidden flex flex-col">
      {/* Mini chart */}
      <div style={{ height: 140 }}>
        <TradingViewMiniChart sym={sym} />
      </div>

      {/* Info */}
      <div className="px-4 py-3 flex flex-col gap-2">
        <div>
          <div className="font-mono font-semibold text-sm">{entry.name}</div>
          <div className="text-[10px] text-slate-500 mt-0.5 leading-tight">{entry.description}</div>
        </div>

        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="text-[9px] text-slate-600 uppercase tracking-wider">ETF proxy</span>
            <span className="font-mono font-bold text-xs text-slate-300 bg-surface-700 px-2 py-0.5 rounded-lg border border-white/5">
              {entry.etf_proxy}
            </span>
          </div>
          <button
            onClick={() => onAnalyse(entry)}
            disabled={isLoading}
            className={clsx(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[11px] font-medium transition-colors",
              isLoading
                ? "bg-brand-500/10 text-brand-400 cursor-wait"
                : "bg-brand-600/80 hover:bg-brand-500 text-white",
            )}
          >
            {isLoading
              ? <Loader2 className="w-3 h-3 animate-spin" />
              : <Brain className="w-3 h-3" />
            }
            {isLoading ? "Analysing…" : "Analyse"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

interface IndicesPageProps {
  paperMode?: boolean;
}

export function IndicesPage({ paperMode = true }: IndicesPageProps) {
  const [activeGroup, setActiveGroup] = useState<string>("us_broad");
  const [signalStates, setSignalStates] = useState<Record<string, SignalState>>({});
  const [latestResult, setLatestResult] = useState<Signal | null>(null);

  const group = INDEX_GROUPS.find((g) => g.id === activeGroup) ?? INDEX_GROUPS[0];

  async function handleAnalyse(entry: IndexEntry) {
    const sym = entry.etf_proxy;
    setSignalStates((prev) => ({
      ...prev,
      [sym]: { symbol: sym, loading: true, signal: null, error: null },
    }));
    setLatestResult(null);

    try {
      const signal = await runSignal(sym, paperMode);
      setSignalStates((prev) => ({
        ...prev,
        [sym]: { symbol: sym, loading: false, signal, error: null },
      }));
      setLatestResult(signal);
    } catch (err) {
      const msg = (err as Error).message ?? "Network error";
      setSignalStates((prev) => ({
        ...prev,
        [sym]: { symbol: sym, loading: false, signal: null, error: msg },
      }));
    }
  }

  const hasAnyLoading = Object.values(signalStates).some((s) => s.loading);
  const errorState = Object.values(signalStates).find((s) => s.error);

  return (
    <div className="space-y-6 max-w-7xl">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-brand-400" />
          Market Indices
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Live index charts via TradingView. Click <strong className="text-slate-300">Analyse</strong> to run the Brain
          on the ETF proxy — all{" "}
          {paperMode ? "rule-based (paper mode)" : "full LLM (live mode)"}.
        </p>
        <div className={clsx(
          "inline-flex items-center gap-1.5 mt-2 px-2.5 py-1 rounded-lg text-[11px] font-mono font-semibold border",
          paperMode
            ? "bg-sky-500/10 border-sky-500/20 text-sky-400"
            : "bg-red-500/10 border-red-500/20 text-red-400",
        )}>
          <span className={clsx("w-1.5 h-1.5 rounded-full", paperMode ? "bg-sky-400" : "bg-red-400 animate-pulse")} />
          {paperMode ? "Paper mode — rule-based analysis" : "Live mode — full LLM debate"}
        </div>
      </div>

      {/* Category tabs */}
      <div className="flex flex-wrap gap-2">
        {INDEX_GROUPS.map((g) => (
          <button
            key={g.id}
            onClick={() => setActiveGroup(g.id)}
            className={clsx(
              "flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-medium transition-all border",
              activeGroup === g.id
                ? g.color
                : "text-slate-500 border-white/5 hover:text-slate-300 hover:border-white/10",
            )}
          >
            {g.label}
            <span className="text-[10px] opacity-60">{g.entries.length}</span>
          </button>
        ))}
      </div>

      {/* Index grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-4">
        {group.entries.map((entry) => (
          <IndexCard
            key={entry.etf_proxy + entry.tv_symbol}
            entry={entry}
            signalState={signalStates[entry.etf_proxy]}
            onAnalyse={handleAnalyse}
          />
        ))}
      </div>

      {/* Status / error */}
      {hasAnyLoading && (
        <div className="flex items-center gap-2 text-xs text-brand-400 font-mono bg-brand-500/10 border border-brand-500/20 rounded-xl px-4 py-3">
          <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
          Running Brain analysis — this takes 10–30 seconds in paper mode, longer in live mode…
        </div>
      )}

      {errorState && (
        <div className="rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm px-4 py-3 font-mono">
          <span className="font-semibold">Error on {errorState.symbol}:</span> {errorState.error}
        </div>
      )}

      {/* Latest signal result */}
      {latestResult && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <ChevronRight className="w-4 h-4 text-brand-400" />
            Latest Signal — {latestResult.symbol}
          </div>
          <SignalCard signal={latestResult} />
        </div>
      )}

      {/* All previous results for the active group */}
      {Object.values(signalStates).filter(
        (s) => s.signal && !s.loading && s.symbol !== latestResult?.symbol
          && group.entries.some((e) => e.etf_proxy === s.symbol),
      ).length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs text-slate-500 font-mono uppercase tracking-wider">
            <Send className="w-3.5 h-3.5" />
            Previous signals (this session)
          </div>
          {Object.values(signalStates)
            .filter(
              (s) => s.signal && !s.loading && s.symbol !== latestResult?.symbol
                && group.entries.some((e) => e.etf_proxy === s.symbol),
            )
            .map((s) => (
              <SignalCard key={s.symbol} signal={s.signal!} />
            ))}
        </div>
      )}
    </div>
  );
}
