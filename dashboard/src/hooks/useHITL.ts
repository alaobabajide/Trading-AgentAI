import { useCallback, useEffect, useRef, useState } from "react";
import {
  HITLMode, UserProfile, SignalTier,
  loadProfile, saveProfile,
} from "../lib/hitl";
import type { Signal } from "../lib/types";

interface HITLState {
  profile:       UserProfile;
  pendingSignal: Signal | null;   // warm signal awaiting veto decision
  vetoSecsLeft:  number;          // countdown for warm signals
  coolOffActive: boolean;         // cool-off timer for oversized manual trades
  coolOffSecsLeft: number;
}

interface HITLActions {
  setMode:          (m: HITLMode) => void;
  updateProfile:    (p: Partial<UserProfile>) => void;
  receiveSignal:    (s: Signal) => "auto_execute" | "veto_window" | "queue_manual";
  vetoSignal:       () => void;
  confirmSignal:    () => void;
  requestManualTrade: (signal: Signal) => boolean;  // returns true if cool-off required
  confirmCoolOff:   () => void;
}

export function useHITL(): HITLState & HITLActions {
  const [profile, setProfile]           = useState<UserProfile>(loadProfile);
  const [pendingSignal, setPending]     = useState<Signal | null>(null);
  const [vetoSecsLeft, setVetoSecs]     = useState(0);
  const [coolOffActive, setCoolOff]     = useState(false);
  const [coolOffSecsLeft, setCoolSecs]  = useState(0);

  const vetoTimer  = useRef<ReturnType<typeof setInterval> | null>(null);
  const coolTimer  = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Veto countdown ──────────────────────────────────────────────────────────
  const clearVeto = useCallback(() => {
    if (vetoTimer.current) clearInterval(vetoTimer.current);
    vetoTimer.current = null;
    setPending(null);
    setVetoSecs(0);
  }, []);

  const startVeto = useCallback((signal: Signal, seconds: number) => {
    setPending(signal);
    setVetoSecs(seconds);
    vetoTimer.current = setInterval(() => {
      setVetoSecs((s) => {
        if (s <= 1) {
          clearInterval(vetoTimer.current!);
          vetoTimer.current = null;
          setPending(null);
          // Auto-confirm after timeout in assisted mode
          return 0;
        }
        return s - 1;
      });
    }, 1000);
  }, [clearVeto]);

  // ── Cool-off countdown ──────────────────────────────────────────────────────
  const clearCool = useCallback(() => {
    if (coolTimer.current) clearInterval(coolTimer.current);
    coolTimer.current = null;
    setCoolOff(false);
    setCoolSecs(0);
  }, []);

  const startCoolOff = useCallback((seconds: number) => {
    setCoolOff(true);
    setCoolSecs(seconds);
    coolTimer.current = setInterval(() => {
      setCoolSecs((s) => {
        if (s <= 1) {
          clearInterval(coolTimer.current!);
          coolTimer.current = null;
          setCoolOff(false);
          return 0;
        }
        return s - 1;
      });
    }, 1000);
  }, []);

  useEffect(() => () => {
    if (vetoTimer.current) clearInterval(vetoTimer.current);
    if (coolTimer.current) clearInterval(coolTimer.current);
  }, []);

  // ── Actions ─────────────────────────────────────────────────────────────────

  const setMode = useCallback((m: HITLMode) => {
    setProfile((p) => {
      const next = { ...p, mode: m };
      saveProfile(next);
      return next;
    });
  }, []);

  const updateProfile = useCallback((partial: Partial<UserProfile>) => {
    setProfile((p) => {
      const next = { ...p, ...partial };
      saveProfile(next);
      return next;
    });
  }, []);

  /**
   * Determines how a new signal should be handled based on its tier + current mode.
   * Returns one of:
   *   "auto_execute"  — HOT signal in Auto mode: execute immediately
   *   "veto_window"   — WARM signal in Assisted mode: start countdown
   *   "queue_manual"  — everything else: requires explicit user click
   */
  const receiveSignal = useCallback((signal: Signal): ReturnType<HITLActions["receiveSignal"]> => {
    const { mode, warmVetoSeconds } = profile;
    const tier: SignalTier = signal.tier ?? "COLD";

    if (mode === "auto" && tier === "HOT") {
      return "auto_execute";
    }
    if (mode === "assisted" && (tier === "HOT" || tier === "WARM")) {
      startVeto(signal, tier === "HOT" ? 5 : warmVetoSeconds);
      return "veto_window";
    }
    // manual mode, or cold signal — always queue
    setPending(signal);
    return "queue_manual";
  }, [profile, startVeto]);

  const vetoSignal    = useCallback(() => clearVeto(), [clearVeto]);
  const confirmSignal = useCallback(() => clearVeto(), [clearVeto]);

  /**
   * Solution 5 — Soft-cap escalation for manual trades that exceed profile limits.
   * Returns true if a cool-off timer was started (caller should block until done).
   */
  const requestManualTrade = useCallback((signal: Signal): boolean => {
    const positionPct = signal.suggested_position_pct * 100;
    if (positionPct > profile.maxPositionPct) {
      startCoolOff(profile.coolOffSeconds);
      return true;
    }
    return false;
  }, [profile, startCoolOff]);

  const confirmCoolOff = useCallback(() => clearCool(), [clearCool]);

  return {
    profile, pendingSignal, vetoSecsLeft, coolOffActive, coolOffSecsLeft,
    setMode, updateProfile, receiveSignal, vetoSignal, confirmSignal,
    requestManualTrade, confirmCoolOff,
  };
}
