-- 0002_idol_kpopping.sql
-- Give each idol a Kpopping identity so the auto-scraper can poll their album feed.
-- kpopping_url = the profile URL the user pasted (kept for reference / re-resolution);
-- kpopping_id  = the resolved Kpopping UUID, used directly as ?idolId=<uuid> against /api/kpics.
-- Existing idols (seeded from database.json) get NULLs and are simply skipped until filled in.

BEGIN;

ALTER TABLE idols ADD COLUMN kpopping_url TEXT;
ALTER TABLE idols ADD COLUMN kpopping_id TEXT;

COMMIT;

-- DOWN
ALTER TABLE idols DROP COLUMN kpopping_url;
ALTER TABLE idols DROP COLUMN kpopping_id;
