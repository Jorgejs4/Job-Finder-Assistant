import { NextResponse } from "next/server";
import { supabaseServer } from "../../../lib/supabase-server";
export async function GET() {
  const supabase = await supabaseServer();
  const { data:{user} } = await supabase.auth.getUser();
  if(!user) return NextResponse.json({error:"No autenticado"},{status:401});
  const {data,error}=await supabase.from("job_runs").select("id,run_key,status,started_at,finished_at,stats,errors").eq("user_id",user.id).order("started_at",{ascending:false}).limit(50);
  if(error) return NextResponse.json({error:error.message},{status:400});
  return NextResponse.json({runs:data||[]});
}
