-- Workflow correction: completion handoff statuses + persisted activity cost lines.

-- CreateEnum values (Postgres)
ALTER TYPE "ActivityStatus" ADD VALUE IF NOT EXISTS 'completion_started';
ALTER TYPE "ActivityStatus" ADD VALUE IF NOT EXISTS 'submitted_to_pl';
ALTER TYPE "ActivityStatus" ADD VALUE IF NOT EXISTS 'returned_by_pl';

-- Activity cost snapshot fields
ALTER TABLE "Activity" ADD COLUMN IF NOT EXISTS "estCostCents" INTEGER NOT NULL DEFAULT 0;
ALTER TABLE "Activity" ADD COLUMN IF NOT EXISTS "costMissing" BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE "Activity" ADD COLUMN IF NOT EXISTS "plReviewNote" TEXT;
ALTER TABLE "Activity" ADD COLUMN IF NOT EXISTS "plReviewedAt" TIMESTAMP(3);
ALTER TABLE "Activity" ADD COLUMN IF NOT EXISTS "plReviewedBy" TEXT;

-- Persisted schedule-time cost lines (CD rate card snapshot per activity)
CREATE TABLE IF NOT EXISTS "ActivityScheduleCostLine" (
    "id" TEXT NOT NULL,
    "activityId" TEXT NOT NULL,
    "costSettingKey" TEXT NOT NULL,
    "label" TEXT NOT NULL,
    "unitCost" INTEGER NOT NULL,
    "quantity" INTEGER NOT NULL DEFAULT 1,
    "amount" INTEGER NOT NULL,
    "costSettingVersion" INTEGER NOT NULL DEFAULT 1,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "ActivityScheduleCostLine_pkey" PRIMARY KEY ("id")
);

CREATE INDEX IF NOT EXISTS "ActivityScheduleCostLine_activityId_idx" ON "ActivityScheduleCostLine"("activityId");

DO $$ BEGIN
  ALTER TABLE "ActivityScheduleCostLine" ADD CONSTRAINT "ActivityScheduleCostLine_activityId_fkey"
    FOREIGN KEY ("activityId") REFERENCES "Activity"("id") ON DELETE CASCADE ON UPDATE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
