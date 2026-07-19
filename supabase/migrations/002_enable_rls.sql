-- Enable RLS on all trendbot tables.
--
-- Access to this schema is service-role only, and the service_role key bypasses
-- RLS, so enabling it does NOT break the bot. It hardens the tables against the
-- anon/authenticated roles. No policies are added on purpose: nothing other than
-- the service role should ever touch these rows.
alter table trendbot.config       enable row level security;
alter table trendbot.signals      enable row level security;
alter table trendbot.orders       enable row level security;
alter table trendbot.positions    enable row level security;
alter table trendbot.equity       enable row level security;
alter table trendbot.decision_log enable row level security;
alter table trendbot.alerts       enable row level security;
