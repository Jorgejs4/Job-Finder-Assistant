import { NextResponse } from "next/server";
import { supabaseServer } from "../../../lib/supabase-server";

export async function GET(req: Request) {
  const s = await supabaseServer();
  const { data: { user } } = await s.auth.getUser();
  if (!user) return NextResponse.json({ error: "No autenticado" }, { status: 401 });
  const p = new URL(req.url).searchParams;
  const limit = Math.min(Math.max(Number(p.get("limit") || 20), 1), 50);
  const offset = Math.max(Number(p.get("offset") || 0), 0);
  const archived = p.get("archived") === "true";
  const unanalyzed = p.get("unanalyzed") === "true";
  const search = (p.get("search") || "").trim().replace(/[,()]/g, " ");
  let query = s.from("jobs")
    .select("id,title,company,canonical_url,location,status,source,description,date_posted,analysis,raw_data,created_at,archived", { count: "exact" })
    .eq("user_id", user.id)
    .eq("archived", archived)
    .order("created_at", { ascending: false })
    .range(offset, offset + limit - 1);
  if (unanalyzed) query = query.or("analysis.is.null,analysis.eq.{}");
  else query = query.not("analysis", "is", null);
  if (search) query = query.or(`title.ilike.%${search}%,company.ilike.%${search}%,location.ilike.%${search}%`);
  const { data, error, count } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  const jobs = (data || []).map((j: any) => {
    const x = { ...(j.raw_data || {}), ...(j.analysis || {}) };
    return { ...j, match_score: Number(x.match_score) || 0, salary_num: Number(String(x.salary || x.salary_min || 0).replace(/[^0-9.]/g, "")) || 0 };
  });
  return NextResponse.json({ jobs, total: count || 0, offset, limit });
}
