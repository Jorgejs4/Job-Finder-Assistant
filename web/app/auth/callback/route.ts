import { NextResponse } from "next/server";
import { supabaseServer } from "../../../lib/supabase-server";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  if (code) await (await supabaseServer()).auth.exchangeCodeForSession(code);
  return NextResponse.redirect(new URL("/", request.url));
}
