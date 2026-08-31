import { NextResponse } from "next/server";
import { supabaseServer } from "../../../lib/supabase-server";

function numberValue(value: unknown) { const n = Number(value); return Number.isFinite(n) ? n : null; }

export async function GET(request: Request) {
  const supabase = await supabaseServer();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "No autenticado" }, { status: 401 });
  const params = new URL(request.url).searchParams;
  const limit = Math.min(Math.max(Number(params.get("limit") || 20), 1), 50);
  const offset = Math.max(Number(params.get("offset") || 0), 0);
  const archived = params.get("archived") === "true";
  const search = (params.get("search") || "").toLowerCase().trim();
  const status = params.get("status") || "Todos";
  const mode = params.get("mode") || "Todos";
  const minMatch = numberValue(params.get("minMatch")) ?? 0;
  const minSalary = numberValue(params.get("minSalary")) ?? 0;
  const maxSalary = numberValue(params.get("maxSalary")) ?? Number.MAX_SAFE_INTEGER;
  const sort = params.get("sort") || "match";
  const all: any[] = [];
  for (let start = 0; ; start += 500) {
    const { data, error } = await supabase.from("jobs").select("id,title,company,location,status,source,archived,description,date_posted,analysis,raw_data,created_at").eq("user_id", user.id).eq("archived", archived).order("created_at", { ascending: false }).range(start, start + 499);
    if (error) return NextResponse.json({ error: error.message }, { status: 400 });
    all.push(...(data || []));
    if (!data || data.length < 500) break;
  }
  let rows = all.map((job: any) => { const fields = { ...(job.raw_data || {}), ...(job.analysis || {}) }; return { ...job, match_score: Number(fields.match_score) || 0, salary_num: Number(String(fields.salary || fields.salary_min || 0).replace(/[^0-9.]/g, "")) || 0, work_mode: fields.work_mode || "No especificado", experience: Number(fields.required_experience ?? fields.experience_hint) || 0 }; }).filter((job: any) => (!search || `${job.title} ${job.company} ${job.location}`.toLowerCase().includes(search)) && (status === "Todos" || job.status === status) && (mode === "Todos" || job.work_mode === mode) && job.match_score >= minMatch && job.salary_num >= minSalary && job.salary_num <= maxSalary);
  rows.sort((a: any, b: any) => sort === "salary_desc" ? b.salary_num - a.salary_num : sort === "salary_asc" ? a.salary_num - b.salary_num : sort === "date" ? String(b.created_at).localeCompare(String(a.created_at)) : b.match_score - a.match_score);
  return NextResponse.json({ jobs: rows.slice(offset, offset + limit), total: rows.length, offset, limit });
}
