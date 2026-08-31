import { NextResponse } from "next/server";
import { supabaseServer } from "../../../lib/supabase-server";

export async function POST(request: Request) {
  const supabase = await supabaseServer();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "No autenticado" }, { status: 401 });
  const body = await request.json().catch(() => ({})) as { workflow?: string; config_json?: string };
  const workflow = body.workflow === "tenant-reanalyze.yml" ? body.workflow : "tenant-scrape.yml";
  const token = process.env.GITHUB_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!token || !repo) return NextResponse.json({ error: "GitHub Actions no configurado en el servidor" }, { status: 503 });
  const profile = await supabase.from("user_profiles").select("preferences").eq("id", user.id).single();
  const config = body.config_json || JSON.stringify(profile.data?.preferences?.workflow || {});
  const response = await fetch(`https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`, { method: "POST", headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ ref: "main", inputs: { user_id: user.id, config_json: config } }) });
  if (!response.ok) return NextResponse.json({ error: `GitHub rechazó el workflow (${response.status})` }, { status: 502 });
  return NextResponse.json({ ok: true, workflow });
}
