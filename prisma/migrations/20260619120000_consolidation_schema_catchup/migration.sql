-- CreateEnum
CREATE TYPE "ImpactYield" AS ENUM ('high', 'healthy', 'weak', 'low', 'insufficient');

-- CreateEnum
CREATE TYPE "CdFlagStatus" AS ENUM ('open', 'acknowledged', 'resolved');

-- AlterEnum
-- This migration adds more than one value to an enum.
-- With PostgreSQL versions 11 and earlier, this is not possible
-- in a single migration. This can be worked around by creating
-- multiple migrations, each migration adding only one value to
-- the enum.


ALTER TYPE "SchoolType" ADD VALUE 'champion';
ALTER TYPE "SchoolType" ADD VALUE 'potential_champion';

-- AlterTable
ALTER TABLE "District" ADD COLUMN     "pcode" TEXT,
ADD COLUMN     "source" TEXT,
ADD COLUMN     "subRegionId" TEXT;

-- AlterTable
ALTER TABLE "EvidenceRecord" ADD COLUMN     "mimeType" TEXT,
ADD COLUMN     "originalName" TEXT;

-- AlterTable
ALTER TABLE "FundRequest" ADD COLUMN     "accountabilityNetsuiteId" TEXT,
ADD COLUMN     "accountabilityReviewedAt" TIMESTAMP(3),
ADD COLUMN     "accountabilityStatus" TEXT,
ADD COLUMN     "accountabilitySubmittedAt" TIMESTAMP(3),
ADD COLUMN     "accountedAmount" DOUBLE PRECISION,
ADD COLUMN     "disburseMethod" TEXT,
ADD COLUMN     "disburseReference" TEXT,
ADD COLUMN     "disbursedAmount" DOUBLE PRECISION,
ADD COLUMN     "disbursedAt" TIMESTAMP(3),
ADD COLUMN     "disbursedByUserId" TEXT,
ADD COLUMN     "returnedAmount" DOUBLE PRECISION;

-- AlterTable
ALTER TABLE "Parish" ADD COLUMN     "confidence" TEXT,
ADD COLUMN     "pcode" TEXT,
ADD COLUMN     "source" TEXT;

-- AlterTable
ALTER TABLE "Partner" ADD COLUMN     "userId" TEXT,
ALTER COLUMN "coverageDistricts" DROP DEFAULT;

-- AlterTable
ALTER TABLE "Region" ADD COLUMN     "latitude" DOUBLE PRECISION,
ADD COLUMN     "longitude" DOUBLE PRECISION,
ADD COLUMN     "pcode" TEXT,
ADD COLUMN     "source" TEXT;

-- AlterTable
ALTER TABLE "School" ADD COLUMN     "countyId" TEXT,
ADD COLUMN     "geographyMatchConfidence" DOUBLE PRECISION,
ADD COLUMN     "geographyMatchStatus" TEXT,
ADD COLUMN     "geographyMatchWarnings" JSONB,
ADD COLUMN     "latitude" DOUBLE PRECISION,
ADD COLUMN     "longitude" DOUBLE PRECISION,
ADD COLUMN     "subRegionId" TEXT,
ADD COLUMN     "uploadedDistrictText" TEXT,
ADD COLUMN     "uploadedParishText" TEXT,
ADD COLUMN     "uploadedRegionText" TEXT,
ADD COLUMN     "uploadedSubCountyText" TEXT;

-- AlterTable
ALTER TABLE "SubCounty" ADD COLUMN     "countyId" TEXT,
ADD COLUMN     "latitude" DOUBLE PRECISION,
ADD COLUMN     "longitude" DOUBLE PRECISION,
ADD COLUMN     "pcode" TEXT,
ADD COLUMN     "source" TEXT;

-- CreateTable
CREATE TABLE "Leave" (
    "id" TEXT NOT NULL,
    "staffProfileId" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "startDate" TEXT NOT NULL,
    "endDate" TEXT NOT NULL,
    "days" INTEGER NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "reason" TEXT,
    "reviewedByUserId" TEXT,
    "reviewedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Leave_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Report" (
    "id" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "scope" TEXT NOT NULL DEFAULT 'country',
    "createdByUserId" TEXT,
    "summaryJson" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Report_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SubRegion" (
    "id" TEXT NOT NULL,
    "regionId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "normalizedName" TEXT NOT NULL,
    "source" TEXT NOT NULL DEFAULT 'CONTROLLED',
    "confidence" TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED',
    "verifiedBy" TEXT,
    "verifiedAt" TIMESTAMP(3),
    "notes" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "SubRegion_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "County" (
    "id" TEXT NOT NULL,
    "districtId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "normalizedName" TEXT NOT NULL,
    "pcode" TEXT,
    "source" TEXT,
    "latitude" DOUBLE PRECISION,
    "longitude" DOUBLE PRECISION,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "County_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Village" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "parishId" TEXT NOT NULL,
    "source" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Village_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "GeographyAlias" (
    "id" TEXT NOT NULL,
    "adminLevel" TEXT NOT NULL,
    "adminId" TEXT NOT NULL,
    "alias" TEXT NOT NULL,
    "normalizedAlias" TEXT NOT NULL,
    "source" TEXT,
    "confidence" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "GeographyAlias_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "BoundaryImportRun" (
    "id" TEXT NOT NULL,
    "sourceName" TEXT NOT NULL,
    "sourceUrl" TEXT,
    "sourceLastModified" TEXT,
    "importedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "importedBy" TEXT,
    "levelCounts" JSONB NOT NULL,
    "checksum" TEXT,
    "status" TEXT NOT NULL,
    "errors" JSONB,
    "warnings" JSONB,

    CONSTRAINT "BoundaryImportRun_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "MonthlyPlan" (
    "id" TEXT NOT NULL,
    "monthIso" TEXT NOT NULL,
    "ownerStaffId" TEXT NOT NULL,
    "ownerName" TEXT,
    "countryId" TEXT NOT NULL DEFAULT 'Uganda',
    "status" TEXT NOT NULL DEFAULT 'draft',
    "submittedAt" TIMESTAMP(3),
    "approvedAt" TIMESTAMP(3),
    "approvedById" TEXT,
    "returnedReason" TEXT,
    "totalCostCents" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "MonthlyPlan_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "MonthlyPlanActivity" (
    "id" TEXT NOT NULL,
    "monthlyPlanId" TEXT NOT NULL,
    "kind" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "weekOfMonth" INTEGER NOT NULL DEFAULT 1,
    "scheduledDate" TEXT,
    "schoolId" TEXT,
    "assigneeId" TEXT,
    "estCostCents" INTEGER NOT NULL DEFAULT 0,
    "status" TEXT NOT NULL DEFAULT 'Planned',
    "interventionArea" TEXT,
    "deliveryType" TEXT,
    "partnerName" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "MonthlyPlanActivity_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CorePlan" (
    "id" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'Active',
    "visitsTarget" INTEGER NOT NULL DEFAULT 4,
    "trainingsTarget" INTEGER NOT NULL DEFAULT 4,
    "visitsCompleted" INTEGER NOT NULL DEFAULT 0,
    "trainingsCompleted" INTEGER NOT NULL DEFAULT 0,
    "baselineAverage" DOUBLE PRECISION,
    "followUpAverage" DOUBLE PRECISION,
    "interventions" JSONB,
    "createdById" TEXT,
    "createdByName" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "CorePlan_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CoreActivitySlot" (
    "id" TEXT NOT NULL,
    "corePlanId" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "intervention" TEXT NOT NULL,
    "activityType" TEXT NOT NULL,
    "sequenceNumber" INTEGER NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'Planned',
    "owner" TEXT NOT NULL DEFAULT 'unassigned',
    "assignedStaffId" TEXT,
    "assignedStaffName" TEXT,
    "assignedPartnerId" TEXT,
    "assignedPartnerName" TEXT,
    "scheduledMonth" TEXT,
    "scheduledWeek" INTEGER,
    "salesforceId" TEXT,
    "completedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "CoreActivitySlot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "BudgetIntelligenceInsight" (
    "id" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "periodType" TEXT NOT NULL,
    "period" TEXT NOT NULL,
    "insightType" TEXT NOT NULL,
    "scopeType" "DecisionScopeType" NOT NULL,
    "scopeId" TEXT,
    "scopeName" TEXT,
    "recommendation" TEXT NOT NULL,
    "reason" TEXT NOT NULL,
    "riskLevel" "DecisionRiskLevel" NOT NULL,
    "impactYield" "ImpactYield" NOT NULL,
    "confidenceLevel" "DecisionConfidenceLevel" NOT NULL,
    "confidenceScore" DOUBLE PRECISION NOT NULL,
    "amountAffected" DOUBLE PRECISION,
    "evidenceSummary" JSONB,
    "financialImplication" TEXT,
    "suggestedAction" TEXT NOT NULL,
    "alternatives" JSONB,
    "metrics" JSONB,
    "riskFlags" TEXT[],
    "status" "DecisionStatus" NOT NULL DEFAULT 'new',
    "reviewedByUserId" TEXT,
    "reviewedByRole" "EdifyRole",
    "reviewedAt" TIMESTAMP(3),
    "reviewNote" TEXT,
    "generatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "BudgetIntelligenceInsight_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "FinanceDecisionNote" (
    "id" TEXT NOT NULL,
    "insightId" TEXT NOT NULL,
    "authorUserId" TEXT NOT NULL,
    "authorRole" "EdifyRole" NOT NULL,
    "note" TEXT NOT NULL,
    "kind" TEXT NOT NULL DEFAULT 'note',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "FinanceDecisionNote_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CdFlag" (
    "id" TEXT NOT NULL,
    "raisedByUserId" TEXT NOT NULL,
    "raisedByName" TEXT,
    "assignedToUserId" TEXT NOT NULL,
    "category" TEXT NOT NULL,
    "scopeType" TEXT,
    "scopeId" TEXT,
    "scopeName" TEXT,
    "note" TEXT NOT NULL,
    "recommendedAction" TEXT,
    "priority" TEXT NOT NULL DEFAULT 'normal',
    "dueDate" TEXT,
    "status" "CdFlagStatus" NOT NULL DEFAULT 'open',
    "resolutionNote" TEXT,
    "resolvedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "CdFlag_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "Leave_staffProfileId_idx" ON "Leave"("staffProfileId");

-- CreateIndex
CREATE INDEX "Leave_status_idx" ON "Leave"("status");

-- CreateIndex
CREATE INDEX "Report_type_idx" ON "Report"("type");

-- CreateIndex
CREATE INDEX "Report_fy_idx" ON "Report"("fy");

-- CreateIndex
CREATE UNIQUE INDEX "SubRegion_name_key" ON "SubRegion"("name");

-- CreateIndex
CREATE UNIQUE INDEX "County_pcode_key" ON "County"("pcode");

-- CreateIndex
CREATE UNIQUE INDEX "County_districtId_name_key" ON "County"("districtId", "name");

-- CreateIndex
CREATE INDEX "Village_parishId_idx" ON "Village"("parishId");

-- CreateIndex
CREATE UNIQUE INDEX "Village_parishId_name_key" ON "Village"("parishId", "name");

-- CreateIndex
CREATE INDEX "GeographyAlias_adminLevel_adminId_idx" ON "GeographyAlias"("adminLevel", "adminId");

-- CreateIndex
CREATE UNIQUE INDEX "GeographyAlias_adminLevel_normalizedAlias_key" ON "GeographyAlias"("adminLevel", "normalizedAlias");

-- CreateIndex
CREATE INDEX "MonthlyPlan_status_idx" ON "MonthlyPlan"("status");

-- CreateIndex
CREATE INDEX "MonthlyPlan_ownerStaffId_idx" ON "MonthlyPlan"("ownerStaffId");

-- CreateIndex
CREATE UNIQUE INDEX "MonthlyPlan_monthIso_ownerStaffId_key" ON "MonthlyPlan"("monthIso", "ownerStaffId");

-- CreateIndex
CREATE INDEX "MonthlyPlanActivity_monthlyPlanId_idx" ON "MonthlyPlanActivity"("monthlyPlanId");

-- CreateIndex
CREATE UNIQUE INDEX "CorePlan_schoolId_key" ON "CorePlan"("schoolId");

-- CreateIndex
CREATE INDEX "CorePlan_status_idx" ON "CorePlan"("status");

-- CreateIndex
CREATE INDEX "CoreActivitySlot_corePlanId_idx" ON "CoreActivitySlot"("corePlanId");

-- CreateIndex
CREATE INDEX "CoreActivitySlot_schoolId_idx" ON "CoreActivitySlot"("schoolId");

-- CreateIndex
CREATE INDEX "BudgetIntelligenceInsight_fy_insightType_idx" ON "BudgetIntelligenceInsight"("fy", "insightType");

-- CreateIndex
CREATE INDEX "BudgetIntelligenceInsight_scopeType_scopeId_idx" ON "BudgetIntelligenceInsight"("scopeType", "scopeId");

-- CreateIndex
CREATE INDEX "BudgetIntelligenceInsight_status_idx" ON "BudgetIntelligenceInsight"("status");

-- CreateIndex
CREATE INDEX "BudgetIntelligenceInsight_impactYield_idx" ON "BudgetIntelligenceInsight"("impactYield");

-- CreateIndex
CREATE INDEX "FinanceDecisionNote_insightId_idx" ON "FinanceDecisionNote"("insightId");

-- CreateIndex
CREATE INDEX "CdFlag_assignedToUserId_status_idx" ON "CdFlag"("assignedToUserId", "status");

-- CreateIndex
CREATE INDEX "CdFlag_raisedByUserId_idx" ON "CdFlag"("raisedByUserId");

-- CreateIndex
CREATE UNIQUE INDEX "District_pcode_key" ON "District"("pcode");

-- CreateIndex
CREATE UNIQUE INDEX "Parish_pcode_key" ON "Parish"("pcode");

-- CreateIndex
CREATE UNIQUE INDEX "Partner_userId_key" ON "Partner"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "Region_pcode_key" ON "Region"("pcode");

-- CreateIndex
CREATE UNIQUE INDEX "SubCounty_pcode_key" ON "SubCounty"("pcode");

-- AddForeignKey
ALTER TABLE "Leave" ADD CONSTRAINT "Leave_staffProfileId_fkey" FOREIGN KEY ("staffProfileId") REFERENCES "StaffProfile"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SubRegion" ADD CONSTRAINT "SubRegion_regionId_fkey" FOREIGN KEY ("regionId") REFERENCES "Region"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "District" ADD CONSTRAINT "District_subRegionId_fkey" FOREIGN KEY ("subRegionId") REFERENCES "SubRegion"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "County" ADD CONSTRAINT "County_districtId_fkey" FOREIGN KEY ("districtId") REFERENCES "District"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SubCounty" ADD CONSTRAINT "SubCounty_countyId_fkey" FOREIGN KEY ("countyId") REFERENCES "County"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Village" ADD CONSTRAINT "Village_parishId_fkey" FOREIGN KEY ("parishId") REFERENCES "Parish"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "MonthlyPlanActivity" ADD CONSTRAINT "MonthlyPlanActivity_monthlyPlanId_fkey" FOREIGN KEY ("monthlyPlanId") REFERENCES "MonthlyPlan"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CoreActivitySlot" ADD CONSTRAINT "CoreActivitySlot_corePlanId_fkey" FOREIGN KEY ("corePlanId") REFERENCES "CorePlan"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Partner" ADD CONSTRAINT "Partner_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "FinanceDecisionNote" ADD CONSTRAINT "FinanceDecisionNote_insightId_fkey" FOREIGN KEY ("insightId") REFERENCES "BudgetIntelligenceInsight"("id") ON DELETE CASCADE ON UPDATE CASCADE;

