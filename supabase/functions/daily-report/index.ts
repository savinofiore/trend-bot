// Daily report edge function. Scheduled via pg_cron; reads the latest equity
// snapshot and open positions and pushes a summary to Telegram.
// Reads only — never places or alters orders.
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

Deno.serve(async () => {
  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { db: { schema: "trendbot" } },
  );

  const { data: equity } = await supabase
    .from("equity")
    .select("at,total_equity,positions")
    .order("at", { ascending: false })
    .limit(1)
    .maybeSingle();

  const { data: alerts } = await supabase
    .from("alerts")
    .select("severity,message,created_at")
    .order("created_at", { ascending: false })
    .limit(5);

  const lines = [
    "📊 trend-bot daily report",
    equity ? `equity: ${equity.total_equity}` : "equity: n/a",
    equity ? `positions: ${JSON.stringify(equity.positions)}` : "",
    ...(alerts ?? []).map((a) => `[${a.severity}] ${a.message}`),
  ].filter(Boolean);

  const token = Deno.env.get("TELEGRAM_BOT_TOKEN");
  const chatId = Deno.env.get("TELEGRAM_CHAT_ID");
  if (token && chatId) {
    await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: lines.join("\n") }),
    });
  }

  return new Response(lines.join("\n"), { headers: { "Content-Type": "text/plain" } });
});
