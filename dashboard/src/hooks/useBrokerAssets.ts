import { useEffect, useState } from "react";
import { apiHeaders } from "../lib/api";

export interface BrokerTabs {
  stocks:  boolean;
  etfs:    boolean;
  crypto:  boolean;
  forex:   boolean;
  ngx:     boolean;
  options: boolean;
  futures: boolean;
  bonds:   boolean;
}

// Safe defaults — mirrors what Alpaca supports; forex/ngx/options/futures/bonds off by default.
const DEFAULT_TABS: BrokerTabs = {
  stocks: true, etfs: true, crypto: true,
  forex: false, ngx: false, options: false, futures: false, bonds: false,
};

export function useBrokerAssets(): { broker: string; tabs: BrokerTabs; loading: boolean } {
  const [broker, setBroker] = useState("");
  const [tabs, setTabs]     = useState<BrokerTabs>(DEFAULT_TABS);
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      const res = await fetch("/api/broker-assets", { headers: apiHeaders() });
      if (res.ok) {
        const data = await res.json();
        setBroker(data.broker ?? "");
        setTabs({ ...DEFAULT_TABS, ...(data.tabs ?? {}) });
      }
    } catch {}
    setLoading(false);
  }

  useEffect(() => {
    load();
    function onUserChanged() { setLoading(true); load(); }
    window.addEventListener("ta:userChanged", onUserChanged);
    return () => window.removeEventListener("ta:userChanged", onUserChanged);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { broker, tabs, loading };
}
