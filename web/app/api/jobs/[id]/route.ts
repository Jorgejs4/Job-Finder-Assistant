import { NextResponse } from "next/server";
import { supabaseServer } from "../../../../lib/supabase-server";

const allowed = new Set(["status", "archived", "archive_reason"]);

export async function PATCH(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const supabase = await supabaseServer();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "No autenticado" }, { status: 401 });
  const input = await request.json().catch(() => null) as Record<string, unknown> | null;
  if (!input || Object.keys(input).some((key) => !allowed.has(key))) return NextResponse.json({ error: "Campos no permitidos" }, { status: 400 });
  const updates = Object.fromEntries(Object.entries(input).filter(([key]) => allowed.has(key)));
  const { data, error } = await supabase.from("jobs").update(updates).eq("id", (await params).id).eq("user_id", user.id).select().single();
  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json({ job: data });
}
