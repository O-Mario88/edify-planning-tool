-- Core-school lifecycle: wire CorePlan/CoreActivitySlot + profile, verification, onboarding.

ALTER TABLE "CorePlan" ADD COLUMN IF NOT EXISTS "baselineSsaRecordId" TEXT;
ALTER TABLE "CorePlan" ADD COLUMN IF NOT EXISTS "followUpSsaRecordId" TEXT;
ALTER TABLE "CorePlan" ADD COLUMN IF NOT EXISTS "followUpScheduledFor" TEXT;
ALTER TABLE "CorePlan" ADD COLUMN IF NOT EXISTS "followUpAssignee" TEXT;

ALTER TABLE "CoreActivitySlot" ADD COLUMN IF NOT EXISTS "scheduledFor" TEXT;
ALTER TABLE "CoreActivitySlot" ADD COLUMN IF NOT EXISTS "activityId" TEXT;
ALTER TABLE "CoreActivitySlot" ADD COLUMN IF NOT EXISTS "evidenceUri" TEXT;
ALTER TABLE "CoreActivitySlot" ADD COLUMN IF NOT EXISTS "evidenceNotes" TEXT;
ALTER TABLE "CoreActivitySlot" ADD COLUMN IF NOT EXISTS "plVerificationStatus" TEXT;
ALTER TABLE "CoreActivitySlot" ADD COLUMN IF NOT EXISTS "iaVerificationStatus" TEXT;
ALTER TABLE "CoreActivitySlot" ADD COLUMN IF NOT EXISTS "accountantStatus" TEXT;
ALTER TABLE "CoreActivitySlot" ADD COLUMN IF NOT EXISTS "teachers" INTEGER;
ALTER TABLE "CoreActivitySlot" ADD COLUMN IF NOT EXISTS "leaders" INTEGER;
ALTER TABLE "CoreActivitySlot" ADD COLUMN IF NOT EXISTS "participants" INTEGER;
ALTER TABLE "CoreActivitySlot" ADD COLUMN IF NOT EXISTS "returnedReason" TEXT;

CREATE TABLE IF NOT EXISTS "CoreSchoolProfile" (
    "id" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "corePlanId" TEXT NOT NULL,
    "coreStartFy" TEXT NOT NULL,
    "championStatus" TEXT NOT NULL DEFAULT 'Not Eligible',
    "status" TEXT NOT NULL DEFAULT 'Active',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "CoreSchoolProfile_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "CoreCandidateVerification" (
    "id" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "ssaRecordId" TEXT NOT NULL,
    "verificationId" TEXT NOT NULL,
    "verifiedById" TEXT NOT NULL,
    "verifiedByName" TEXT NOT NULL,
    "verifiedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "status" TEXT NOT NULL,
    "comments" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "CoreCandidateVerification_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "CoreSchoolOnboarding" (
    "id" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "corePlanId" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "previousSchoolType" TEXT NOT NULL,
    "baselineSsaRecordId" TEXT NOT NULL,
    "baselineAverageScore" DOUBLE PRECISION NOT NULL,
    "onboardedById" TEXT NOT NULL,
    "onboardedByName" TEXT NOT NULL,
    "onboardedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "onboardingReason" TEXT,
    "status" TEXT NOT NULL DEFAULT 'Onboarded',
    CONSTRAINT "CoreSchoolOnboarding_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX IF NOT EXISTS "CoreSchoolProfile_schoolId_key" ON "CoreSchoolProfile"("schoolId");
CREATE UNIQUE INDEX IF NOT EXISTS "CoreSchoolProfile_corePlanId_key" ON "CoreSchoolProfile"("corePlanId");
CREATE UNIQUE INDEX IF NOT EXISTS "CoreCandidateVerification_schoolId_key" ON "CoreCandidateVerification"("schoolId");
CREATE UNIQUE INDEX IF NOT EXISTS "CoreSchoolOnboarding_schoolId_key" ON "CoreSchoolOnboarding"("schoolId");
CREATE UNIQUE INDEX IF NOT EXISTS "CoreSchoolOnboarding_corePlanId_key" ON "CoreSchoolOnboarding"("corePlanId");

ALTER TABLE "CoreSchoolProfile" DROP CONSTRAINT IF EXISTS "CoreSchoolProfile_corePlanId_fkey";
ALTER TABLE "CoreSchoolProfile" ADD CONSTRAINT "CoreSchoolProfile_corePlanId_fkey" FOREIGN KEY ("corePlanId") REFERENCES "CorePlan"("id") ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE "CoreSchoolOnboarding" DROP CONSTRAINT IF EXISTS "CoreSchoolOnboarding_corePlanId_fkey";
ALTER TABLE "CoreSchoolOnboarding" ADD CONSTRAINT "CoreSchoolOnboarding_corePlanId_fkey" FOREIGN KEY ("corePlanId") REFERENCES "CorePlan"("id") ON DELETE CASCADE ON UPDATE CASCADE;
