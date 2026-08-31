"use client";
import { supabaseBrowser } from "../lib/supabase-browser";
export default function SignOut() { return <button className="button secondary" onClick={() => supabaseBrowser().auth.signOut().then(() => location.assign("/login"))}>Cerrar sesión</button>; }
