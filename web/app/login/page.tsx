"use client";

import { supabaseBrowser } from "../../lib/supabase-browser";

export default function LoginPage() {
  async function login() {
    const supabase = supabaseBrowser();
    await supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo: `${window.location.origin}/auth/callback` } });
  }
  return <main className="login card"><h1>Job Finder Assistant</h1><p className="muted">Accede a tu dashboard de empleo.</p><button className="button" onClick={login}>Continuar con Google</button></main>;
}
