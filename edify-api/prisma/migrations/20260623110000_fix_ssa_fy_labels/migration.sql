-- Align SSA record FY labels with the operational FY of dateOfSsa (FY starts Oct 1).
UPDATE "SsaRecord"
SET fy = '2026'
WHERE "dateOfSsa" >= TIMESTAMP '2025-10-01'
  AND "dateOfSsa" < TIMESTAMP '2026-10-01'
  AND fy IS DISTINCT FROM '2026'
  AND "deletedAt" IS NULL;
