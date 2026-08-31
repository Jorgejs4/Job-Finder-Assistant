import { supabaseServer } from "../lib/supabase-server";
import SignOut from "./sign-out";

export default async function DashboardPage() {
  const supabase = await supabaseServer();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return <main className="login"><a className="button" href="/login">Iniciar sesión</a></main>;
  const { data: jobs } = await supabase.from("jobs").select("id,title,company,location,status,source,archived,description,created_at").eq("archived", false).order("created_at", { ascending: false }).limit(100);
  return <main className="shell"><header className="topbar"><div><div className="brand">🔍 Job Finder Assistant</div><span className="muted">{user.email}</span></div><SignOut /></header><h1>Mis ofertas</h1><p className="muted">{jobs?.length ?? 0} ofertas activas</p>{jobs?.map((job) => <article className="card job" key={job.id}><div><h2>{job.title || "Sin título"}</h2><p>{job.company || "Empresa no indicada"} · {job.location || "Ubicación no indicada"}</p><p className="muted">{job.source} {job.description ? `· ${job.description.slice(0, 180)}…` : ""}</p></div><span className="badge">{job.status}</span></article>)}</main>;
}
