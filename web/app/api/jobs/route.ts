import { NextResponse } from "next/server";
import { supabaseServer } from "../../../lib/supabase-server";

export async function GET(request: Request) {
  const supabase = await supabaseServer();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "No autenticado" }, { status: 401 });
  const url = new URL(request.url);
  const limit = Math.min(Math.max(Number(url.searchParams.get("limit") || 20), 1), 50);
  const offset = Math.max(Number(url.searchParams.get("offset") || 0), 0);
  const archived = url.searchParams.get("archived") === "true";
  const search = (url.searchParams.get("search") || "").trim();
  const status = url.searchParams.get("status");
  let query = supabase.from("jobs").select("id,title,company,location,status,source,archived,description,date_posted,analysis,created_at", { count: "exact" }).eq("user_id", user.id).eq("archived", archived).order("created_at", { ascending: false }).range(offset, offset + limit - 1);
  if (status) query = query.eq("status", status);
  if (search) query = query.or(`title.ilike.%${search}%,company.ilike.%${search}%,location.ilike.%${search}%`);
  const { data, count, error } = await query;
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json({ jobs: data || [], total: count || 0, offset, limit });
}
