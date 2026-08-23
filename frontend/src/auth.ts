import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";

const url = (import.meta.env.VITE_SUPABASE_URL ?? "").trim();
const anonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY ?? "").trim();

export const authEnabled = Boolean(url && anonKey);
export const supabase: SupabaseClient | null = authEnabled
  ? createClient(url, anonKey)
  : null;

export async function getSession(): Promise<Session | null> {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session;
}

export function onAuthStateChange(callback: (session: Session | null) => void): () => void {
  if (!supabase) return () => undefined;
  const { data } = supabase.auth.onAuthStateChange((_event, session) => callback(session));
  return () => data.subscription.unsubscribe();
}

export async function signIn(email: string, password: string) {
  if (!supabase) throw new Error("Supabase authentication is not configured.");
  return supabase.auth.signInWithPassword({ email, password });
}

export async function signUp(email: string, password: string) {
  if (!supabase) throw new Error("Supabase authentication is not configured.");
  return supabase.auth.signUp({ email, password });
}

export async function signOut(): Promise<void> {
  if (supabase) await supabase.auth.signOut();
}
