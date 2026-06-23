-- Communication system rebuild (messages + notifications + command-center).
-- Spec §11 (fund routing), §13 (alerts), §16 (models), §19 (event log).

-- ── FundRequestStatus: multi-hop routing chain (PL → CD → RVP → Accountant) ──
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'draft';
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'submitted_to_pl';
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'approved_by_pl';
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'submitted_to_cd';
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'approved_by_cd';
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'submitted_to_rvp';
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'approved_by_rvp';
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'sent_to_accountant';
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'closed';
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'returned_by_pl';
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'returned_by_cd';
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'returned_by_rvp';
ALTER TYPE "FundRequestStatus" ADD VALUE IF NOT EXISTS 'returned_by_accountant';

-- ── Notification: provenance + action label + expiry (spec §16) ──
ALTER TABLE "Notification" ADD COLUMN IF NOT EXISTS "recipientRole" "EdifyRole";
ALTER TABLE "Notification" ADD COLUMN IF NOT EXISTS "actionLabel" TEXT;
ALTER TABLE "Notification" ADD COLUMN IF NOT EXISTS "sourceEventType" TEXT;
ALTER TABLE "Notification" ADD COLUMN IF NOT EXISTS "sourceEventId" TEXT;
ALTER TABLE "Notification" ADD COLUMN IF NOT EXISTS "expiresAt" TIMESTAMP(3);
ALTER TABLE "Notification" ADD COLUMN IF NOT EXISTS "readAt" TIMESTAMP(3);
CREATE INDEX IF NOT EXISTS "Notification_sourceEventId_idx" ON "Notification"("sourceEventId");

-- ── MessageContextPolicy (spec §6/§16) ──
CREATE TABLE IF NOT EXISTS "MessageContextPolicy" (
  "id" TEXT NOT NULL,
  "senderRole" "EdifyRole" NOT NULL,
  "recipientRole" "EdifyRole" NOT NULL,
  "allowedContextType" TEXT NOT NULL,
  "label" TEXT,
  "requiresLinkedRecord" BOOLEAN NOT NULL DEFAULT false,
  "allowedRecordTypes" TEXT[] DEFAULT ARRAY[]::TEXT[],
  "isActive" BOOLEAN NOT NULL DEFAULT true,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "MessageContextPolicy_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX IF NOT EXISTS "MessageContextPolicy_senderRole_recipientRole_allowedContext_key"
  ON "MessageContextPolicy"("senderRole", "recipientRole", "allowedContextType");
CREATE INDEX IF NOT EXISTS "MessageContextPolicy_senderRole_recipientRole_isActive_idx"
  ON "MessageContextPolicy"("senderRole", "recipientRole", "isActive");

-- ── DomainEventLog (spec §16/§19) ──
CREATE TABLE IF NOT EXISTS "DomainEventLog" (
  "id" TEXT NOT NULL,
  "eventType" TEXT NOT NULL,
  "aggregateType" TEXT,
  "aggregateId" TEXT,
  "actorId" TEXT,
  "payload" JSONB,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "processedAt" TIMESTAMP(3),
  CONSTRAINT "DomainEventLog_pkey" PRIMARY KEY ("id")
);
CREATE INDEX IF NOT EXISTS "DomainEventLog_eventType_idx" ON "DomainEventLog"("eventType");
CREATE INDEX IF NOT EXISTS "DomainEventLog_aggregateType_aggregateId_idx" ON "DomainEventLog"("aggregateType", "aggregateId");
CREATE INDEX IF NOT EXISTS "DomainEventLog_processedAt_idx" ON "DomainEventLog"("processedAt");

-- ── CommandCenterAlert (spec §13) ──
CREATE TABLE IF NOT EXISTS "CommandCenterAlert" (
  "id" TEXT NOT NULL,
  "alertType" TEXT NOT NULL,
  "severity" "NotificationPriority" NOT NULL DEFAULT 'high',
  "scope" TEXT,
  "contextType" TEXT,
  "contextId" TEXT,
  "title" TEXT NOT NULL,
  "body" TEXT,
  "targetRoute" TEXT,
  "conditionHash" TEXT NOT NULL,
  "status" TEXT NOT NULL DEFAULT 'open',
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  "resolvedAt" TIMESTAMP(3),
  CONSTRAINT "CommandCenterAlert_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX IF NOT EXISTS "CommandCenterAlert_conditionHash_key" ON "CommandCenterAlert"("conditionHash");
CREATE INDEX IF NOT EXISTS "CommandCenterAlert_status_idx" ON "CommandCenterAlert"("status");
CREATE INDEX IF NOT EXISTS "CommandCenterAlert_alertType_status_idx" ON "CommandCenterAlert"("alertType", "status");

-- ── CommandCenterAlertDismissal (spec §13) ──
CREATE TABLE IF NOT EXISTS "CommandCenterAlertDismissal" (
  "id" TEXT NOT NULL,
  "alertId" TEXT NOT NULL,
  "userId" TEXT NOT NULL,
  "dismissedUntil" TIMESTAMP(3) NOT NULL,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "CommandCenterAlertDismissal_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX IF NOT EXISTS "CommandCenterAlertDismissal_alertId_userId_key" ON "CommandCenterAlertDismissal"("alertId", "userId");
CREATE INDEX IF NOT EXISTS "CommandCenterAlertDismissal_userId_idx" ON "CommandCenterAlertDismissal"("userId");
ALTER TABLE "CommandCenterAlertDismissal"
  ADD CONSTRAINT "CommandCenterAlertDismissal_alertId_fkey"
  FOREIGN KEY ("alertId") REFERENCES "CommandCenterAlert"("id") ON DELETE CASCADE ON UPDATE CASCADE;
