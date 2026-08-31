import { supabaseServer } from "../lib/supabase-server";
import Dashboard from "./dashboard";
import SignOut from "./sign-out";

export default async function Home() {
  const supabase = await supabaseServer();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return <main className="login"><a className="button" href="/login">Iniciar sesión</a></main>;
  return <Dashboard email={user.email || ""} signOut={<SignOut />} />;
}
