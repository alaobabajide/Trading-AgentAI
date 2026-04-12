import { useEffect, useRef, useState } from "react";

/** Re-renders every `ms` milliseconds — drives live chart updates. */
export function useLiveTick(ms = 2000) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
  return tick;
}

/** Returns the latest version of `factory()` rebuilt on each tick. */
export function useLiveData<T>(factory: () => T, ms = 2000): T {
  const [data, setData] = useState<T>(factory);
  const factoryRef = useRef(factory);
  factoryRef.current = factory;
  useEffect(() => {
    const id = setInterval(() => setData(factoryRef.current()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return data;
}
