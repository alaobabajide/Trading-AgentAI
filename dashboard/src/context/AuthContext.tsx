import { createContext, useContext, useEffect, useState } from "react";
import type { Session, User } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { setActiveToken, setActiveUserId } from "../lib/api";

interface AuthContextValue {
  user: User | null;
  session: Session | null;
  loading: boolean;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  session: null,
  loading: true,
  signOut: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Hydrate from existing session (e.g. page refresh)
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setUser(session?.user ?? null);
      setActiveUserId(session?.user?.id ?? null);
      setActiveToken(session?.access_token ?? null);
      setLoading(false);
    });

    // Keep in sync: sign-in, sign-out, token auto-refresh.
    // setActiveUserId before setActiveToken so storage keys are namespaced before
    // any hook that reads localStorage on the same tick.
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
      setUser(session?.user ?? null);
      setActiveUserId(session?.user?.id ?? null);
      setActiveToken(session?.access_token ?? null);
    });

    // Central 401 interceptor — api.ts dispatches "ta:auth401" when any API
    // call receives a 401, meaning the token was rejected by the backend.
    // Sign out immediately so the login screen appears rather than silent failures.
    const handle401 = () => { supabase.auth.signOut(); };
    window.addEventListener("ta:auth401", handle401);

    return () => {
      subscription.unsubscribe();
      window.removeEventListener("ta:auth401", handle401);
    };
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        loading,
        signOut: async () => { await supabase.auth.signOut(); },
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
