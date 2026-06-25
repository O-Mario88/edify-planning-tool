-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "public";

-- CreateEnum
CREATE TYPE "EdifyRole" AS ENUM ('CCEO', 'CountryProgramLead', 'CountryDirector', 'RegionalVicePresident', 'ImpactAssessment', 'ProgramAccountant', 'HumanResources', 'ProjectCoordinator', 'PartnerAdmin', 'PartnerFieldOfficer', 'Admin');

-- CreateEnum
CREATE TYPE "SchoolType" AS ENUM ('client', 'core', 'potential_core', 'champion', 'potential_champion', 'other');

-- CreateEnum
CREATE TYPE "AccountOwnerStatus" AS ENUM ('matched', 'unmatched', 'pending');

-- CreateEnum
CREATE TYPE "DuplicateStatus" AS ENUM ('none', 'potential', 'confirmed', 'not_duplicate', 'merged');

-- CreateEnum
CREATE TYPE "ClusterStatus" AS ENUM ('unclustered', 'clustered', 'needs_review');

-- CreateEnum
CREATE TYPE "ClusterRecordStatus" AS ENUM ('active', 'needs_review', 'inactive');

-- CreateEnum
CREATE TYPE "ClusterType" AS ENUM ('client', 'core', 'mixed');

-- CreateEnum
CREATE TYPE "SsaStatus" AS ENUM ('not_done', 'scheduled', 'partner_assigned', 'done');

-- CreateEnum
CREATE TYPE "PlanningReadiness" AS ENUM ('locked', 'limited', 'ready');

-- CreateEnum
CREATE TYPE "SsaIntervention" AS ENUM ('teaching_and_learning', 'financial_health', 'christlike_behaviour', 'exposure_to_word_of_god', 'government_requirements', 'leadership', 'education_technology', 'learning_environment');

-- CreateEnum
CREATE TYPE "ActivityType" AS ENUM ('school_visit', 'follow_up_visit', 'coaching_visit', 'in_school_support', 'training', 'school_improvement_training', 'cluster_meeting', 'cluster_training', 'ssa_activity', 'project_activity', 'partner_activity', 'core_visit', 'core_training');

-- CreateEnum
CREATE TYPE "ClusterMeetingSlot" AS ENUM ('sit', 'first_meeting', 'second_meeting', 'third_meeting');

-- CreateEnum
CREATE TYPE "DeliveryType" AS ENUM ('staff', 'partner');

-- CreateEnum
CREATE TYPE "ActivityStatus" AS ENUM ('not_planned', 'planned', 'scheduled', 'assigned_to_partner', 'partner_scheduled', 'in_progress', 'completion_started', 'evidence_uploaded', 'evidence_accepted', 'salesforce_id_required', 'submitted_to_pl', 'returned_by_pl', 'awaiting_ia_verification', 'ia_verified', 'accountant_confirmed', 'completed', 'returned', 'rejected', 'rescheduled', 'cancelled', 'deferred');

-- CreateEnum
CREATE TYPE "EvidenceStatus" AS ENUM ('none', 'uploaded', 'accepted', 'returned', 'rejected');

-- CreateEnum
CREATE TYPE "EvidenceKind" AS ENUM ('visit_form', 'school_stamp', 'attendance_form', 'meeting_minutes', 'resolutions', 'evaluation_form', 'assessment_form', 'photo', 'pdf', 'project_report', 'coaching_notes');

-- CreateEnum
CREATE TYPE "VerificationStatus" AS ENUM ('pending', 'confirmed', 'returned', 'flagged');

-- CreateEnum
CREATE TYPE "SalesforceActivityType" AS ENUM ('visit', 'training');

-- CreateEnum
CREATE TYPE "SalesforceSyncStatus" AS ENUM ('not_synced', 'pending', 'synced', 'error');

-- CreateEnum
CREATE TYPE "PaymentStatus" AS ENUM ('none', 'pending_ia', 'ia_confirmed', 'pl_approval_required', 'pl_approved', 'accountant_cleared', 'paid', 'netsuite_accountability', 'closed', 'rejected');

-- CreateEnum
CREATE TYPE "PaymentPath" AS ENUM ('partner', 'staff');

-- CreateEnum
CREATE TYPE "ProjectCategory" AS ENUM ('intervention_specific', 'pilot', 'selective_limited');

-- CreateEnum
CREATE TYPE "NotificationPriority" AS ENUM ('low', 'normal', 'high', 'urgent');

-- CreateEnum
CREATE TYPE "MessageStatus" AS ENUM ('unread', 'read', 'archived');

-- CreateEnum
CREATE TYPE "BudgetView" AS ENUM ('summary', 'detailed');

-- CreateEnum
CREATE TYPE "StaffOnboardingState" AS ENUM ('pending', 'active', 'suspended');

-- CreateEnum
CREATE TYPE "SsaCollectorType" AS ENUM ('staff', 'partner', 'ia', 'imported_previous_fy', 'system_migration');

-- CreateEnum
CREATE TYPE "TargetType" AS ENUM ('SCHOOL_REACH', 'STAFF_DIRECT_SUPPORT', 'PARTNER_SUPPORT', 'TRAINING', 'SSA', 'SCHOOL_VISIT', 'MSCS', 'EXAM_RESULTS', 'CORE_PACKAGE', 'PROJECT_SUPPORT', 'IA_VERIFICATION', 'ACCOUNTABILITY');

-- CreateEnum
CREATE TYPE "TargetScopeType" AS ENUM ('country', 'region', 'district', 'cluster', 'staff', 'pl_team', 'partner', 'project', 'school_type');

-- CreateEnum
CREATE TYPE "TargetUnit" AS ENUM ('count', 'percentage');

-- CreateEnum
CREATE TYPE "MscsReviewStatus" AS ENUM ('draft', 'submitted', 'reviewed', 'approved', 'returned', 'rejected', 'donor_ready');

-- CreateEnum
CREATE TYPE "ExamCollectionStatus" AS ENUM ('missing', 'collected', 'validated', 'returned', 'approved');

-- CreateEnum
CREATE TYPE "DebriefType" AS ENUM ('staff', 'partner', 'merged');

-- CreateEnum
CREATE TYPE "DebriefStatus" AS ENUM ('draft', 'submitted', 'reviewed', 'merged', 'returned', 'archived');

-- CreateEnum
CREATE TYPE "FundRequestPeriod" AS ENUM ('weekly', 'monthly', 'quarterly', 'annual');

-- CreateEnum
CREATE TYPE "FundRequestStatus" AS ENUM ('submitted', 'approved', 'returned', 'rejected', 'disbursed', 'draft', 'submitted_to_pl', 'approved_by_pl', 'submitted_to_cd', 'approved_by_cd', 'submitted_to_rvp', 'approved_by_rvp', 'sent_to_accountant', 'closed', 'returned_by_pl', 'returned_by_cd', 'returned_by_rvp', 'returned_by_accountant');

-- CreateEnum
CREATE TYPE "DecisionType" AS ENUM ('recruitment', 'staff_addition', 'partner', 'staff_hr', 'regional_investment');

-- CreateEnum
CREATE TYPE "DecisionScopeType" AS ENUM ('country', 'region', 'district', 'sub_county', 'cluster', 'school', 'staff', 'partner');

-- CreateEnum
CREATE TYPE "DecisionRiskLevel" AS ENUM ('low', 'medium', 'high', 'critical');

-- CreateEnum
CREATE TYPE "DecisionConfidenceLevel" AS ENUM ('high', 'medium', 'low', 'insufficient');

-- CreateEnum
CREATE TYPE "DecisionStatus" AS ENUM ('new', 'under_review', 'accepted', 'accepted_with_conditions', 'rejected', 'deferred', 'converted_to_action_plan');

-- CreateEnum
CREATE TYPE "ImpactYield" AS ENUM ('high', 'healthy', 'weak', 'low', 'insufficient');

-- CreateEnum
CREATE TYPE "CdFlagStatus" AS ENUM ('open', 'acknowledged', 'resolved');

-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "passwordHash" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "roles" "EdifyRole"[],
    "activeRole" "EdifyRole" NOT NULL,
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "failedLoginCount" INTEGER NOT NULL DEFAULT 0,
    "lockedUntil" TIMESTAMP(3),
    "mfaEnabled" BOOLEAN NOT NULL DEFAULT false,
    "mfaSecret" TEXT,
    "passwordResetTokenHash" TEXT,
    "passwordResetExpires" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Permission" (
    "id" TEXT NOT NULL,
    "key" TEXT NOT NULL,
    "description" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Permission_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "RolePermission" (
    "id" TEXT NOT NULL,
    "role" "EdifyRole" NOT NULL,
    "permissionId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "RolePermission_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "StaffProfile" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "staffNumber" TEXT,
    "title" TEXT,
    "primaryDistrictId" TEXT,
    "onboardingState" "StaffOnboardingState" NOT NULL DEFAULT 'pending',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "StaffProfile_pkey" PRIMARY KEY ("id")
);

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
CREATE TABLE "StaffSupervisorAssignment" (
    "id" TEXT NOT NULL,
    "superviseeId" TEXT NOT NULL,
    "supervisorId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "StaffSupervisorAssignment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "StaffGeographyAssignment" (
    "id" TEXT NOT NULL,
    "staffId" TEXT NOT NULL,
    "regionId" TEXT,
    "districtId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "StaffGeographyAssignment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "StaffSchoolAssignment" (
    "id" TEXT NOT NULL,
    "staffId" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "StaffSchoolAssignment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "StaffSupportCapacity" (
    "id" TEXT NOT NULL,
    "staffId" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "maxDirectSchoolsSupported" INTEGER NOT NULL,
    "setByUserId" TEXT NOT NULL,
    "setByRole" "EdifyRole" NOT NULL,
    "effectiveFrom" TIMESTAMP(3),
    "effectiveTo" TIMESTAMP(3),
    "notes" TEXT,
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "StaffSupportCapacity_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AssignmentAudit" (
    "id" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "schoolId" TEXT,
    "activityId" TEXT,
    "assignerId" TEXT NOT NULL,
    "assignerRole" "EdifyRole" NOT NULL,
    "assignedToType" TEXT NOT NULL,
    "assignedStaffId" TEXT,
    "assignedPartnerId" TEXT,
    "allowed" BOOLEAN NOT NULL,
    "blockedReason" TEXT,
    "overrideUsed" BOOLEAN NOT NULL DEFAULT false,
    "overrideReason" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AssignmentAudit_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "StaffTargetProfile" (
    "id" TEXT NOT NULL,
    "staffId" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "visitsTarget" INTEGER NOT NULL DEFAULT 0,
    "trainingsTarget" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "StaffTargetProfile_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Region" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "code" TEXT,
    "pcode" TEXT,
    "source" TEXT,
    "latitude" DOUBLE PRECISION,
    "longitude" DOUBLE PRECISION,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Region_pkey" PRIMARY KEY ("id")
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
CREATE TABLE "District" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "code" TEXT,
    "pcode" TEXT,
    "source" TEXT,
    "regionId" TEXT NOT NULL,
    "subRegionId" TEXT,
    "latitude" DOUBLE PRECISION,
    "longitude" DOUBLE PRECISION,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "District_pkey" PRIMARY KEY ("id")
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
CREATE TABLE "SubCounty" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "seeded" BOOLEAN NOT NULL DEFAULT false,
    "pcode" TEXT,
    "source" TEXT,
    "latitude" DOUBLE PRECISION,
    "longitude" DOUBLE PRECISION,
    "districtId" TEXT NOT NULL,
    "countyId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "SubCounty_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Parish" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "pcode" TEXT,
    "source" TEXT,
    "confidence" TEXT,
    "subCountyId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Parish_pkey" PRIMARY KEY ("id")
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
CREATE TABLE "School" (
    "id" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "regionId" TEXT NOT NULL,
    "districtId" TEXT NOT NULL,
    "subCountyId" TEXT,
    "parishId" TEXT,
    "subRegionId" TEXT,
    "countyId" TEXT,
    "latitude" DOUBLE PRECISION,
    "longitude" DOUBLE PRECISION,
    "uploadedRegionText" TEXT,
    "uploadedDistrictText" TEXT,
    "uploadedSubCountyText" TEXT,
    "uploadedParishText" TEXT,
    "geographyMatchStatus" TEXT,
    "geographyMatchConfidence" DOUBLE PRECISION,
    "geographyMatchWarnings" JSONB,
    "shippingAddress" TEXT,
    "schoolPhone" TEXT,
    "primaryContactName" TEXT,
    "primaryContactPhone" TEXT,
    "enrollment" INTEGER,
    "schoolType" "SchoolType" NOT NULL DEFAULT 'client',
    "accountOwnerId" TEXT,
    "accountOwnerNameRaw" TEXT,
    "accountOwnerStatus" "AccountOwnerStatus" NOT NULL DEFAULT 'pending',
    "duplicateStatus" "DuplicateStatus" NOT NULL DEFAULT 'none',
    "clusterId" TEXT,
    "clusterStatus" "ClusterStatus" NOT NULL DEFAULT 'unclustered',
    "currentFySsaStatus" "SsaStatus" NOT NULL DEFAULT 'not_done',
    "planningReadiness" "PlanningReadiness" NOT NULL DEFAULT 'locked',
    "salesforceAccountId" TEXT,
    "salesforceSyncStatus" "SalesforceSyncStatus" NOT NULL DEFAULT 'not_synced',
    "salesforceLastSyncedAt" TIMESTAMP(3),
    "salesforceSyncError" TEXT,
    "createdByIa" BOOLEAN NOT NULL DEFAULT false,
    "uploadBatchId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "School_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "UploadBatch" (
    "id" TEXT NOT NULL,
    "source" TEXT NOT NULL DEFAULT 'manual',
    "fileName" TEXT,
    "uploadedBy" TEXT NOT NULL,
    "rowCount" INTEGER NOT NULL DEFAULT 0,
    "acceptedCount" INTEGER NOT NULL DEFAULT 0,
    "flaggedCount" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "UploadBatch_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SchoolAccountOwnerUploadMap" (
    "id" TEXT NOT NULL,
    "uploadBatchId" TEXT NOT NULL,
    "schoolIdRaw" TEXT NOT NULL,
    "ownerNameRaw" TEXT NOT NULL,
    "matchedStaffId" TEXT,
    "matched" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "SchoolAccountOwnerUploadMap_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SchoolDuplicateCandidate" (
    "id" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "candidateId" TEXT NOT NULL,
    "score" INTEGER NOT NULL,
    "reasons" TEXT[],
    "resolved" BOOLEAN NOT NULL DEFAULT false,
    "resolution" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "SchoolDuplicateCandidate_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Cluster" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "regionId" TEXT NOT NULL,
    "districtId" TEXT NOT NULL,
    "subCountyId" TEXT,
    "subCountyName" TEXT,
    "clusterType" "ClusterType" NOT NULL DEFAULT 'mixed',
    "status" "ClusterRecordStatus" NOT NULL DEFAULT 'active',
    "overrideReason" TEXT,
    "responsibleStaffId" TEXT,
    "clusterLeaderName" TEXT,
    "clusterLeaderPhone" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "Cluster_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ClusterSubCounty" (
    "id" TEXT NOT NULL,
    "clusterId" TEXT NOT NULL,
    "subCountyId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ClusterSubCounty_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SchoolClusterAssignment" (
    "id" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "clusterId" TEXT NOT NULL,
    "assignedBy" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "SchoolClusterAssignment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SsaRecord" (
    "id" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "dateOfSsa" TIMESTAMP(3) NOT NULL,
    "fy" TEXT NOT NULL,
    "quarter" TEXT NOT NULL,
    "newEnrollment" INTEGER,
    "averageScore" DOUBLE PRECISION,
    "salesforceId" TEXT,
    "verificationStatus" "VerificationStatus" NOT NULL DEFAULT 'pending',
    "collectorType" "SsaCollectorType" NOT NULL DEFAULT 'staff',
    "verificationSource" TEXT,
    "collectedByUserId" TEXT,
    "collectedByPartnerId" TEXT,
    "verifiedByUserId" TEXT,
    "verifiedAt" TIMESTAMP(3),
    "qaReviewedByUserId" TEXT,
    "qaReviewedAt" TIMESTAMP(3),
    "uploadedBy" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "SsaRecord_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SsaScore" (
    "id" TEXT NOT NULL,
    "ssaRecordId" TEXT NOT NULL,
    "intervention" "SsaIntervention" NOT NULL,
    "score" DOUBLE PRECISION NOT NULL,

    CONSTRAINT "SsaScore_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SchoolEnrollmentHistory" (
    "id" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "enrollment" INTEGER NOT NULL,
    "recordedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "SchoolEnrollmentHistory_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Activity" (
    "id" TEXT NOT NULL,
    "activityType" "ActivityType" NOT NULL,
    "schoolId" TEXT,
    "clusterId" TEXT,
    "projectId" TEXT,
    "fy" TEXT NOT NULL,
    "quarter" TEXT NOT NULL,
    "month" INTEGER,
    "week" INTEGER,
    "scheduledDate" TIMESTAMP(3),
    "plannedMonth" INTEGER,
    "plannedWeek" INTEGER,
    "responsibleStaffId" TEXT,
    "monitoredByStaffId" TEXT,
    "assignedPartnerId" TEXT,
    "deliveryType" "DeliveryType" NOT NULL DEFAULT 'staff',
    "clusterSlot" "ClusterMeetingSlot",
    "purposeIntervention" "SsaIntervention",
    "status" "ActivityStatus" NOT NULL DEFAULT 'not_planned',
    "evidenceStatus" "EvidenceStatus" NOT NULL DEFAULT 'none',
    "salesforceActivityId" TEXT,
    "salesforceActivityType" "SalesforceActivityType",
    "iaVerificationStatus" "VerificationStatus" NOT NULL DEFAULT 'pending',
    "iaConfirmedAt" TIMESTAMP(3),
    "iaConfirmedBy" TEXT,
    "paymentStatus" "PaymentStatus" NOT NULL DEFAULT 'none',
    "rescheduleCount" INTEGER NOT NULL DEFAULT 0,
    "lastReason" TEXT,
    "estCostCents" INTEGER NOT NULL DEFAULT 0,
    "costMissing" BOOLEAN NOT NULL DEFAULT false,
    "plReviewNote" TEXT,
    "plReviewedAt" TIMESTAMP(3),
    "plReviewedBy" TEXT,
    "teachersAttended" INTEGER,
    "leadersAttended" INTEGER,
    "otherParticipants" INTEGER,
    "nextMeetingDate" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "Activity_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ActivityScheduleCostLine" (
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

-- CreateTable
CREATE TABLE "EvidenceRecord" (
    "id" TEXT NOT NULL,
    "activityId" TEXT NOT NULL,
    "kind" "EvidenceKind" NOT NULL,
    "uri" TEXT NOT NULL,
    "originalName" TEXT,
    "mimeType" TEXT,
    "notes" TEXT,
    "uploadedBy" TEXT NOT NULL,
    "status" "EvidenceStatus" NOT NULL DEFAULT 'uploaded',
    "reviewedBy" TEXT,
    "reviewedAt" TIMESTAMP(3),
    "reviewNote" TEXT,
    "scanStatus" TEXT NOT NULL DEFAULT 'pending',
    "quarantined" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "EvidenceRecord_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ActivityCompletionVerification" (
    "id" TEXT NOT NULL,
    "activityId" TEXT NOT NULL,
    "salesforceId" TEXT NOT NULL,
    "enteredBy" TEXT NOT NULL,
    "enteredAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "status" "VerificationStatus" NOT NULL DEFAULT 'pending',
    "iaActorId" TEXT,
    "iaActionAt" TIMESTAMP(3),
    "iaNote" TEXT,

    CONSTRAINT "ActivityCompletionVerification_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PaymentRequest" (
    "id" TEXT NOT NULL,
    "activityId" TEXT NOT NULL,
    "path" "PaymentPath" NOT NULL,
    "amount" DOUBLE PRECISION,
    "status" "PaymentStatus" NOT NULL DEFAULT 'pending_ia',
    "netsuiteExpenseId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "PaymentRequest_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PaymentActionLog" (
    "id" TEXT NOT NULL,
    "paymentRequestId" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "actorId" TEXT NOT NULL,
    "note" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PaymentActionLog_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PaymentDisbursement" (
    "id" TEXT NOT NULL,
    "paymentRequestId" TEXT NOT NULL,
    "amount" DOUBLE PRECISION NOT NULL,
    "clearedBy" TEXT NOT NULL,
    "paidAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "reference" TEXT,

    CONSTRAINT "PaymentDisbursement_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AnnualPlan" (
    "id" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "ownerStaffId" TEXT,
    "status" TEXT NOT NULL DEFAULT 'draft',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "AnnualPlan_pkey" PRIMARY KEY ("id")
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
    "baselineSsaRecordId" TEXT,
    "followUpSsaRecordId" TEXT,
    "followUpScheduledFor" TEXT,
    "followUpAssignee" TEXT,
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
    "scheduledFor" TEXT,
    "salesforceId" TEXT,
    "activityId" TEXT,
    "evidenceUri" TEXT,
    "evidenceNotes" TEXT,
    "plVerificationStatus" TEXT,
    "iaVerificationStatus" TEXT,
    "accountantStatus" TEXT,
    "teachers" INTEGER,
    "leaders" INTEGER,
    "participants" INTEGER,
    "returnedReason" TEXT,
    "completedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "CoreActivitySlot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CoreSchoolProfile" (
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

-- CreateTable
CREATE TABLE "CoreCandidateVerification" (
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

-- CreateTable
CREATE TABLE "CoreSchoolOnboarding" (
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

-- CreateTable
CREATE TABLE "AnnualPlanActivity" (
    "id" TEXT NOT NULL,
    "annualPlanId" TEXT NOT NULL,
    "activityType" "ActivityType" NOT NULL,
    "schoolId" TEXT,
    "clusterId" TEXT,
    "quarter" TEXT NOT NULL,
    "month" INTEGER,
    "week" INTEGER,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AnnualPlanActivity_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ActivityBudgetLine" (
    "id" TEXT NOT NULL,
    "annualPlanActivityId" TEXT NOT NULL,
    "costSettingKey" TEXT NOT NULL,
    "quantity" DOUBLE PRECISION NOT NULL DEFAULT 1,
    "unitCost" DOUBLE PRECISION NOT NULL,
    "amount" DOUBLE PRECISION NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ActivityBudgetLine_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "BudgetVersion" (
    "id" TEXT NOT NULL,
    "annualPlanId" TEXT NOT NULL,
    "version" INTEGER NOT NULL DEFAULT 1,
    "total" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "BudgetVersion_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "BudgetApproval" (
    "id" TEXT NOT NULL,
    "budgetVersionId" TEXT NOT NULL,
    "approverId" TEXT NOT NULL,
    "decision" TEXT NOT NULL,
    "note" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "BudgetApproval_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "MonthlyFundRequest" (
    "id" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "month" INTEGER NOT NULL,
    "staffId" TEXT,
    "amount" DOUBLE PRECISION NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'submitted',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "MonthlyFundRequest_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CostSetting" (
    "id" TEXT NOT NULL,
    "key" TEXT NOT NULL,
    "label" TEXT NOT NULL,
    "unitCost" DOUBLE PRECISION NOT NULL,
    "fy" TEXT,
    "version" INTEGER NOT NULL DEFAULT 1,
    "createdBy" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "CostSetting_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "CostSettingHistory" (
    "id" TEXT NOT NULL,
    "key" TEXT NOT NULL,
    "label" TEXT NOT NULL,
    "oldUnitCost" DOUBLE PRECISION,
    "newUnitCost" DOUBLE PRECISION NOT NULL,
    "version" INTEGER NOT NULL,
    "fy" TEXT,
    "changedByUserId" TEXT NOT NULL,
    "reason" TEXT,
    "changedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CostSettingHistory_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Project" (
    "id" TEXT NOT NULL,
    "code" TEXT,
    "name" TEXT NOT NULL,
    "category" "ProjectCategory" NOT NULL,
    "intervention" "SsaIntervention",
    "managerStaffId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "Project_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ProjectSchoolAssignment" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ProjectSchoolAssignment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ProjectPartnerAssignment" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "partnerId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ProjectPartnerAssignment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ProjectImpactSnapshot" (
    "id" TEXT NOT NULL,
    "projectId" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "metricsJson" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ProjectImpactSnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Partner" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "regionName" TEXT,
    "trainsOn" TEXT[],
    "notes" TEXT,
    "contactPerson" TEXT,
    "email" TEXT,
    "phone" TEXT,
    "coverageDistricts" TEXT[],
    "contractStatus" TEXT,
    "onboardedByUserId" TEXT,
    "onboardedAt" TIMESTAMP(3),
    "isCertified" BOOLEAN NOT NULL DEFAULT false,
    "certificationStatus" TEXT,
    "expertiseAreas" TEXT[],
    "activeStatus" BOOLEAN NOT NULL DEFAULT true,
    "userId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "Partner_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "MessageThread" (
    "id" TEXT NOT NULL,
    "subject" TEXT NOT NULL,
    "contextType" TEXT,
    "contextId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "MessageThread_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Message" (
    "id" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "senderId" TEXT NOT NULL,
    "recipientId" TEXT,
    "body" TEXT NOT NULL,
    "category" TEXT,
    "contextType" TEXT,
    "contextId" TEXT,
    "targetRoute" TEXT,
    "priority" "NotificationPriority" NOT NULL DEFAULT 'normal',
    "actionRequired" BOOLEAN NOT NULL DEFAULT false,
    "status" "MessageStatus" NOT NULL DEFAULT 'unread',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Message_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Notification" (
    "id" TEXT NOT NULL,
    "recipientId" TEXT NOT NULL,
    "recipientRole" "EdifyRole",
    "title" TEXT NOT NULL,
    "body" TEXT,
    "contextType" TEXT,
    "contextId" TEXT,
    "targetRoute" TEXT,
    "actionLabel" TEXT,
    "actionRequired" BOOLEAN NOT NULL DEFAULT false,
    "priority" "NotificationPriority" NOT NULL DEFAULT 'normal',
    "status" "MessageStatus" NOT NULL DEFAULT 'unread',
    "sourceEventType" TEXT,
    "sourceEventId" TEXT,
    "expiresAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "readAt" TIMESTAMP(3),

    CONSTRAINT "Notification_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "MessageContextPolicy" (
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

-- CreateTable
CREATE TABLE "DomainEventLog" (
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

-- CreateTable
CREATE TABLE "CommandCenterAlert" (
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

-- CreateTable
CREATE TABLE "CommandCenterAlertDismissal" (
    "id" TEXT NOT NULL,
    "alertId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "dismissedUntil" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CommandCenterAlertDismissal_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AuditLog" (
    "id" TEXT NOT NULL,
    "seq" BIGSERIAL NOT NULL,
    "action" TEXT NOT NULL,
    "subjectKind" TEXT,
    "subjectId" TEXT,
    "actorId" TEXT,
    "actorRole" "EdifyRole",
    "payload" JSONB,
    "ipAddress" TEXT,
    "userAgent" TEXT,
    "correlationId" TEXT,
    "success" BOOLEAN NOT NULL DEFAULT true,
    "reason" TEXT,
    "prevHash" TEXT,
    "hash" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AuditLog_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TargetSetting" (
    "id" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "targetType" "TargetType" NOT NULL,
    "scopeType" "TargetScopeType" NOT NULL,
    "scopeId" TEXT,
    "targetValue" DOUBLE PRECISION,
    "targetUnit" "TargetUnit" NOT NULL DEFAULT 'percentage',
    "targetPercentage" DOUBLE PRECISION,
    "quarterDistribution" JSONB,
    "setByUserId" TEXT NOT NULL,
    "setByRole" "EdifyRole" NOT NULL,
    "effectiveFrom" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "effectiveTo" TIMESTAMP(3),
    "notes" TEXT,
    "isActive" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "TargetSetting_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "MostSignificantChangeStory" (
    "id" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "quarter" TEXT,
    "schoolId" TEXT,
    "clusterId" TEXT,
    "districtId" TEXT,
    "regionId" TEXT,
    "submittedByStaffId" TEXT,
    "submittedByRole" "EdifyRole",
    "relatedInterventionId" TEXT,
    "relatedProjectId" TEXT,
    "storyTitle" TEXT NOT NULL,
    "storySummary" TEXT,
    "storyText" TEXT,
    "evidenceAttachmentId" TEXT,
    "consentStatus" TEXT,
    "reviewStatus" "MscsReviewStatus" NOT NULL DEFAULT 'draft',
    "reviewedBy" TEXT,
    "approvedBy" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "MostSignificantChangeStory_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ExamResultCollection" (
    "id" TEXT NOT NULL,
    "schoolId" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "examType" TEXT,
    "examYear" INTEGER,
    "collectionDate" TIMESTAMP(3),
    "collectedByStaffId" TEXT,
    "uploadedByIA" TEXT,
    "status" "ExamCollectionStatus" NOT NULL DEFAULT 'missing',
    "attachmentId" TEXT,
    "resultsSummaryJson" JSONB,
    "notes" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "ExamResultCollection_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DailyDebrief" (
    "id" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "date" TIMESTAMP(3) NOT NULL,
    "submittedByUserId" TEXT NOT NULL,
    "submittedByRole" "EdifyRole" NOT NULL,
    "staffId" TEXT,
    "partnerId" TEXT,
    "debriefType" "DebriefType" NOT NULL DEFAULT 'staff',
    "status" "DebriefStatus" NOT NULL DEFAULT 'submitted',
    "summary" TEXT,
    "whatHappened" TEXT,
    "whatWentWell" TEXT,
    "whatDidNotGoWell" TEXT,
    "blockers" TEXT[],
    "blockerOther" TEXT,
    "supportNeeded" TEXT,
    "recommendations" TEXT,
    "nextAction" TEXT,
    "linkedSchoolIds" TEXT[],
    "linkedClusterIds" TEXT[],
    "linkedPartnerIds" TEXT[],
    "linkedProjectIds" TEXT[],
    "linkedActivityIds" TEXT[],
    "parentDebriefId" TEXT,
    "mergedIntoDebriefId" TEXT,
    "reviewedByUserId" TEXT,
    "reviewedAt" TIMESTAMP(3),
    "reviewNote" TEXT,
    "submittedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "deletedAt" TIMESTAMP(3),

    CONSTRAINT "DailyDebrief_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DailyDebriefRecipient" (
    "id" TEXT NOT NULL,
    "debriefId" TEXT NOT NULL,
    "recipientUserId" TEXT NOT NULL,
    "recipientRole" "EdifyRole" NOT NULL,
    "routingReason" TEXT,
    "actionRequired" BOOLEAN NOT NULL DEFAULT false,
    "readAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "DailyDebriefRecipient_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "FundRequest" (
    "id" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "period" "FundRequestPeriod" NOT NULL,
    "periodKey" TEXT NOT NULL,
    "scope" TEXT NOT NULL,
    "submittedByUserId" TEXT NOT NULL,
    "submittedByRole" "EdifyRole" NOT NULL,
    "totalAmount" DOUBLE PRECISION NOT NULL,
    "activityCount" INTEGER NOT NULL,
    "status" "FundRequestStatus" NOT NULL DEFAULT 'submitted',
    "reviewedByUserId" TEXT,
    "reviewedAt" TIMESTAMP(3),
    "reviewNote" TEXT,
    "disbursedAmount" DOUBLE PRECISION,
    "disbursedAt" TIMESTAMP(3),
    "disbursedByUserId" TEXT,
    "disburseMethod" TEXT,
    "disburseReference" TEXT,
    "accountedAmount" DOUBLE PRECISION,
    "returnedAmount" DOUBLE PRECISION,
    "accountabilityStatus" TEXT,
    "accountabilityNetsuiteId" TEXT,
    "accountabilitySubmittedAt" TIMESTAMP(3),
    "accountabilityReviewedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "FundRequest_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "LeadershipDecisionInsight" (
    "id" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "quarter" TEXT,
    "decisionType" "DecisionType" NOT NULL,
    "scopeType" "DecisionScopeType" NOT NULL,
    "scopeId" TEXT,
    "scopeName" TEXT,
    "recommendation" TEXT NOT NULL,
    "reason" TEXT NOT NULL,
    "riskLevel" "DecisionRiskLevel" NOT NULL,
    "confidenceLevel" "DecisionConfidenceLevel" NOT NULL,
    "confidenceScore" DOUBLE PRECISION NOT NULL,
    "evidenceSummary" JSONB,
    "contextAdjustment" TEXT,
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

    CONSTRAINT "LeadershipDecisionInsight_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DecisionEvidencePoint" (
    "id" TEXT NOT NULL,
    "insightId" TEXT NOT NULL,
    "metricName" TEXT NOT NULL,
    "metricValue" TEXT NOT NULL,
    "comparisonValue" TEXT,
    "sourceType" TEXT NOT NULL,
    "sourceId" TEXT,
    "explanation" TEXT,
    "weight" TEXT NOT NULL DEFAULT 'supporting',
    "tone" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "DecisionEvidencePoint_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "DecisionNote" (
    "id" TEXT NOT NULL,
    "insightId" TEXT NOT NULL,
    "authorUserId" TEXT NOT NULL,
    "authorRole" "EdifyRole" NOT NULL,
    "note" TEXT NOT NULL,
    "kind" TEXT NOT NULL DEFAULT 'note',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "DecisionNote_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "StaffContextProfile" (
    "id" TEXT NOT NULL,
    "staffId" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "quarter" TEXT NOT NULL DEFAULT 'FY',
    "schoolLoad" INTEGER NOT NULL DEFAULT 0,
    "clientSchoolLoad" INTEGER NOT NULL DEFAULT 0,
    "coreSchoolLoad" INTEGER NOT NULL DEFAULT 0,
    "partnerManagementLoad" INTEGER NOT NULL DEFAULT 0,
    "projectLoad" INTEGER NOT NULL DEFAULT 0,
    "districtSpread" INTEGER NOT NULL DEFAULT 0,
    "subCountySpread" INTEGER NOT NULL DEFAULT 0,
    "rescheduleLoad" INTEGER NOT NULL DEFAULT 0,
    "evidenceBacklog" INTEGER NOT NULL DEFAULT 0,
    "geographyDifficulty" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "ruralityScore" DOUBLE PRECISION,
    "distanceBurden" DOUBLE PRECISION,
    "teamContributionScore" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "contextDifficultyScore" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "dataConfidence" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "computedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "StaffContextProfile_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PartnerPerformanceProfile" (
    "id" TEXT NOT NULL,
    "partnerId" TEXT NOT NULL,
    "fy" TEXT NOT NULL,
    "quarter" TEXT NOT NULL DEFAULT 'FY',
    "assignedActivities" INTEGER NOT NULL DEFAULT 0,
    "completedActivities" INTEGER NOT NULL DEFAULT 0,
    "targetAchievementRate" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "evidenceAcceptanceRate" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "iaConfirmationRate" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "returnedEvidenceCount" INTEGER NOT NULL DEFAULT 0,
    "rescheduleRate" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "overdueRate" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "capacityUtilization" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "interventionImpactScore" DOUBLE PRECISION,
    "assignedInterventions" TEXT[],
    "recommendationStatus" TEXT,
    "dataConfidence" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "computedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PartnerPerformanceProfile_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "RecruitmentReadinessProfile" (
    "id" TEXT NOT NULL,
    "scopeType" "DecisionScopeType" NOT NULL,
    "scopeId" TEXT NOT NULL DEFAULT '',
    "scopeName" TEXT,
    "fy" TEXT NOT NULL,
    "quarter" TEXT NOT NULL DEFAULT 'FY',
    "ssaCompletionRate" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "targetAchievementRate" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "staffCapacityScore" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "partnerCapacityScore" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "dataQualityScore" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "impactScore" DOUBLE PRECISION,
    "schoolsTotal" INTEGER NOT NULL DEFAULT 0,
    "schoolsMissingSsa" INTEGER NOT NULL DEFAULT 0,
    "schoolsUnclustered" INTEGER NOT NULL DEFAULT 0,
    "recruitmentRecommendation" TEXT,
    "dataConfidence" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "computedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "RecruitmentReadinessProfile_pkey" PRIMARY KEY ("id")
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
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE UNIQUE INDEX "Permission_key_key" ON "Permission"("key");

-- CreateIndex
CREATE UNIQUE INDEX "RolePermission_role_permissionId_key" ON "RolePermission"("role", "permissionId");

-- CreateIndex
CREATE UNIQUE INDEX "StaffProfile_userId_key" ON "StaffProfile"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "StaffProfile_staffNumber_key" ON "StaffProfile"("staffNumber");

-- CreateIndex
CREATE INDEX "Leave_staffProfileId_idx" ON "Leave"("staffProfileId");

-- CreateIndex
CREATE INDEX "Leave_status_idx" ON "Leave"("status");

-- CreateIndex
CREATE INDEX "Report_type_idx" ON "Report"("type");

-- CreateIndex
CREATE INDEX "Report_fy_idx" ON "Report"("fy");

-- CreateIndex
CREATE INDEX "StaffSupervisorAssignment_supervisorId_idx" ON "StaffSupervisorAssignment"("supervisorId");

-- CreateIndex
CREATE UNIQUE INDEX "StaffSupervisorAssignment_superviseeId_supervisorId_key" ON "StaffSupervisorAssignment"("superviseeId", "supervisorId");

-- CreateIndex
CREATE INDEX "StaffGeographyAssignment_staffId_idx" ON "StaffGeographyAssignment"("staffId");

-- CreateIndex
CREATE UNIQUE INDEX "StaffSchoolAssignment_staffId_schoolId_key" ON "StaffSchoolAssignment"("staffId", "schoolId");

-- CreateIndex
CREATE INDEX "StaffSupportCapacity_fy_idx" ON "StaffSupportCapacity"("fy");

-- CreateIndex
CREATE UNIQUE INDEX "StaffSupportCapacity_staffId_fy_key" ON "StaffSupportCapacity"("staffId", "fy");

-- CreateIndex
CREATE INDEX "AssignmentAudit_assignerId_idx" ON "AssignmentAudit"("assignerId");

-- CreateIndex
CREATE INDEX "AssignmentAudit_schoolId_idx" ON "AssignmentAudit"("schoolId");

-- CreateIndex
CREATE INDEX "AssignmentAudit_createdAt_idx" ON "AssignmentAudit"("createdAt");

-- CreateIndex
CREATE UNIQUE INDEX "StaffTargetProfile_staffId_fy_key" ON "StaffTargetProfile"("staffId", "fy");

-- CreateIndex
CREATE UNIQUE INDEX "Region_name_key" ON "Region"("name");

-- CreateIndex
CREATE UNIQUE INDEX "Region_code_key" ON "Region"("code");

-- CreateIndex
CREATE UNIQUE INDEX "Region_pcode_key" ON "Region"("pcode");

-- CreateIndex
CREATE UNIQUE INDEX "SubRegion_name_key" ON "SubRegion"("name");

-- CreateIndex
CREATE UNIQUE INDEX "District_code_key" ON "District"("code");

-- CreateIndex
CREATE UNIQUE INDEX "District_pcode_key" ON "District"("pcode");

-- CreateIndex
CREATE UNIQUE INDEX "District_regionId_name_key" ON "District"("regionId", "name");

-- CreateIndex
CREATE UNIQUE INDEX "County_pcode_key" ON "County"("pcode");

-- CreateIndex
CREATE UNIQUE INDEX "County_districtId_name_key" ON "County"("districtId", "name");

-- CreateIndex
CREATE UNIQUE INDEX "SubCounty_pcode_key" ON "SubCounty"("pcode");

-- CreateIndex
CREATE UNIQUE INDEX "SubCounty_districtId_name_key" ON "SubCounty"("districtId", "name");

-- CreateIndex
CREATE UNIQUE INDEX "Parish_pcode_key" ON "Parish"("pcode");

-- CreateIndex
CREATE UNIQUE INDEX "Parish_subCountyId_name_key" ON "Parish"("subCountyId", "name");

-- CreateIndex
CREATE INDEX "Village_parishId_idx" ON "Village"("parishId");

-- CreateIndex
CREATE UNIQUE INDEX "Village_parishId_name_key" ON "Village"("parishId", "name");

-- CreateIndex
CREATE INDEX "GeographyAlias_adminLevel_adminId_idx" ON "GeographyAlias"("adminLevel", "adminId");

-- CreateIndex
CREATE UNIQUE INDEX "GeographyAlias_adminLevel_normalizedAlias_key" ON "GeographyAlias"("adminLevel", "normalizedAlias");

-- CreateIndex
CREATE UNIQUE INDEX "School_schoolId_key" ON "School"("schoolId");

-- CreateIndex
CREATE INDEX "School_regionId_idx" ON "School"("regionId");

-- CreateIndex
CREATE INDEX "School_districtId_idx" ON "School"("districtId");

-- CreateIndex
CREATE INDEX "School_clusterId_idx" ON "School"("clusterId");

-- CreateIndex
CREATE INDEX "School_schoolType_idx" ON "School"("schoolType");

-- CreateIndex
CREATE UNIQUE INDEX "SchoolDuplicateCandidate_schoolId_candidateId_key" ON "SchoolDuplicateCandidate"("schoolId", "candidateId");

-- CreateIndex
CREATE INDEX "Cluster_districtId_idx" ON "Cluster"("districtId");

-- CreateIndex
CREATE INDEX "Cluster_subCountyId_idx" ON "Cluster"("subCountyId");

-- CreateIndex
CREATE INDEX "ClusterSubCounty_subCountyId_idx" ON "ClusterSubCounty"("subCountyId");

-- CreateIndex
CREATE UNIQUE INDEX "ClusterSubCounty_clusterId_subCountyId_key" ON "ClusterSubCounty"("clusterId", "subCountyId");

-- CreateIndex
CREATE UNIQUE INDEX "SchoolClusterAssignment_schoolId_clusterId_key" ON "SchoolClusterAssignment"("schoolId", "clusterId");

-- CreateIndex
CREATE INDEX "SsaRecord_schoolId_idx" ON "SsaRecord"("schoolId");

-- CreateIndex
CREATE INDEX "SsaRecord_fy_idx" ON "SsaRecord"("fy");

-- CreateIndex
CREATE INDEX "SsaRecord_collectorType_idx" ON "SsaRecord"("collectorType");

-- CreateIndex
CREATE INDEX "SsaRecord_verificationStatus_idx" ON "SsaRecord"("verificationStatus");

-- CreateIndex
CREATE UNIQUE INDEX "SsaScore_ssaRecordId_intervention_key" ON "SsaScore"("ssaRecordId", "intervention");

-- CreateIndex
CREATE UNIQUE INDEX "SchoolEnrollmentHistory_schoolId_fy_key" ON "SchoolEnrollmentHistory"("schoolId", "fy");

-- CreateIndex
CREATE INDEX "Activity_schoolId_idx" ON "Activity"("schoolId");

-- CreateIndex
CREATE INDEX "Activity_clusterId_idx" ON "Activity"("clusterId");

-- CreateIndex
CREATE INDEX "Activity_fy_quarter_idx" ON "Activity"("fy", "quarter");

-- CreateIndex
CREATE INDEX "Activity_responsibleStaffId_idx" ON "Activity"("responsibleStaffId");

-- CreateIndex
CREATE INDEX "Activity_status_idx" ON "Activity"("status");

-- CreateIndex
CREATE INDEX "Activity_scheduledDate_idx" ON "Activity"("scheduledDate");

-- CreateIndex
CREATE INDEX "Activity_assignedPartnerId_idx" ON "Activity"("assignedPartnerId");

-- CreateIndex
CREATE INDEX "Activity_iaVerificationStatus_paymentStatus_idx" ON "Activity"("iaVerificationStatus", "paymentStatus");

-- CreateIndex
CREATE INDEX "Activity_evidenceStatus_idx" ON "Activity"("evidenceStatus");

-- CreateIndex
CREATE INDEX "ActivityScheduleCostLine_activityId_idx" ON "ActivityScheduleCostLine"("activityId");

-- CreateIndex
CREATE INDEX "EvidenceRecord_activityId_idx" ON "EvidenceRecord"("activityId");

-- CreateIndex
CREATE INDEX "EvidenceRecord_quarantined_idx" ON "EvidenceRecord"("quarantined");

-- CreateIndex
CREATE UNIQUE INDEX "ActivityCompletionVerification_activityId_key" ON "ActivityCompletionVerification"("activityId");

-- CreateIndex
CREATE UNIQUE INDEX "PaymentRequest_activityId_key" ON "PaymentRequest"("activityId");

-- CreateIndex
CREATE UNIQUE INDEX "PaymentDisbursement_paymentRequestId_key" ON "PaymentDisbursement"("paymentRequestId");

-- CreateIndex
CREATE UNIQUE INDEX "AnnualPlan_fy_ownerStaffId_key" ON "AnnualPlan"("fy", "ownerStaffId");

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
CREATE UNIQUE INDEX "CoreSchoolProfile_schoolId_key" ON "CoreSchoolProfile"("schoolId");

-- CreateIndex
CREATE UNIQUE INDEX "CoreSchoolProfile_corePlanId_key" ON "CoreSchoolProfile"("corePlanId");

-- CreateIndex
CREATE UNIQUE INDEX "CoreCandidateVerification_schoolId_key" ON "CoreCandidateVerification"("schoolId");

-- CreateIndex
CREATE UNIQUE INDEX "CoreSchoolOnboarding_schoolId_key" ON "CoreSchoolOnboarding"("schoolId");

-- CreateIndex
CREATE UNIQUE INDEX "CoreSchoolOnboarding_corePlanId_key" ON "CoreSchoolOnboarding"("corePlanId");

-- CreateIndex
CREATE UNIQUE INDEX "CostSetting_key_key" ON "CostSetting"("key");

-- CreateIndex
CREATE INDEX "CostSettingHistory_key_idx" ON "CostSettingHistory"("key");

-- CreateIndex
CREATE INDEX "CostSettingHistory_changedAt_idx" ON "CostSettingHistory"("changedAt");

-- CreateIndex
CREATE UNIQUE INDEX "Project_code_key" ON "Project"("code");

-- CreateIndex
CREATE UNIQUE INDEX "ProjectSchoolAssignment_projectId_schoolId_key" ON "ProjectSchoolAssignment"("projectId", "schoolId");

-- CreateIndex
CREATE UNIQUE INDEX "ProjectPartnerAssignment_projectId_partnerId_key" ON "ProjectPartnerAssignment"("projectId", "partnerId");

-- CreateIndex
CREATE UNIQUE INDEX "Partner_userId_key" ON "Partner"("userId");

-- CreateIndex
CREATE INDEX "Message_recipientId_status_idx" ON "Message"("recipientId", "status");

-- CreateIndex
CREATE INDEX "Notification_recipientId_status_idx" ON "Notification"("recipientId", "status");

-- CreateIndex
CREATE INDEX "Notification_sourceEventId_idx" ON "Notification"("sourceEventId");

-- CreateIndex
CREATE INDEX "MessageContextPolicy_senderRole_recipientRole_isActive_idx" ON "MessageContextPolicy"("senderRole", "recipientRole", "isActive");

-- CreateIndex
CREATE UNIQUE INDEX "MessageContextPolicy_senderRole_recipientRole_allowedContex_key" ON "MessageContextPolicy"("senderRole", "recipientRole", "allowedContextType");

-- CreateIndex
CREATE INDEX "DomainEventLog_eventType_idx" ON "DomainEventLog"("eventType");

-- CreateIndex
CREATE INDEX "DomainEventLog_aggregateType_aggregateId_idx" ON "DomainEventLog"("aggregateType", "aggregateId");

-- CreateIndex
CREATE INDEX "DomainEventLog_processedAt_idx" ON "DomainEventLog"("processedAt");

-- CreateIndex
CREATE UNIQUE INDEX "CommandCenterAlert_conditionHash_key" ON "CommandCenterAlert"("conditionHash");

-- CreateIndex
CREATE INDEX "CommandCenterAlert_status_idx" ON "CommandCenterAlert"("status");

-- CreateIndex
CREATE INDEX "CommandCenterAlert_alertType_status_idx" ON "CommandCenterAlert"("alertType", "status");

-- CreateIndex
CREATE INDEX "CommandCenterAlertDismissal_userId_idx" ON "CommandCenterAlertDismissal"("userId");

-- CreateIndex
CREATE UNIQUE INDEX "CommandCenterAlertDismissal_alertId_userId_key" ON "CommandCenterAlertDismissal"("alertId", "userId");

-- CreateIndex
CREATE INDEX "AuditLog_subjectKind_subjectId_idx" ON "AuditLog"("subjectKind", "subjectId");

-- CreateIndex
CREATE INDEX "AuditLog_actorId_idx" ON "AuditLog"("actorId");

-- CreateIndex
CREATE INDEX "AuditLog_createdAt_idx" ON "AuditLog"("createdAt");

-- CreateIndex
CREATE INDEX "AuditLog_seq_idx" ON "AuditLog"("seq");

-- CreateIndex
CREATE INDEX "AuditLog_action_idx" ON "AuditLog"("action");

-- CreateIndex
CREATE INDEX "AuditLog_correlationId_idx" ON "AuditLog"("correlationId");

-- CreateIndex
CREATE INDEX "TargetSetting_fy_targetType_idx" ON "TargetSetting"("fy", "targetType");

-- CreateIndex
CREATE INDEX "TargetSetting_scopeType_scopeId_idx" ON "TargetSetting"("scopeType", "scopeId");

-- CreateIndex
CREATE INDEX "TargetSetting_isActive_idx" ON "TargetSetting"("isActive");

-- CreateIndex
CREATE INDEX "MostSignificantChangeStory_fy_quarter_idx" ON "MostSignificantChangeStory"("fy", "quarter");

-- CreateIndex
CREATE INDEX "MostSignificantChangeStory_schoolId_idx" ON "MostSignificantChangeStory"("schoolId");

-- CreateIndex
CREATE INDEX "MostSignificantChangeStory_reviewStatus_idx" ON "MostSignificantChangeStory"("reviewStatus");

-- CreateIndex
CREATE INDEX "ExamResultCollection_fy_idx" ON "ExamResultCollection"("fy");

-- CreateIndex
CREATE INDEX "ExamResultCollection_schoolId_idx" ON "ExamResultCollection"("schoolId");

-- CreateIndex
CREATE INDEX "ExamResultCollection_status_idx" ON "ExamResultCollection"("status");

-- CreateIndex
CREATE INDEX "DailyDebrief_fy_date_idx" ON "DailyDebrief"("fy", "date");

-- CreateIndex
CREATE INDEX "DailyDebrief_submittedByUserId_idx" ON "DailyDebrief"("submittedByUserId");

-- CreateIndex
CREATE INDEX "DailyDebrief_status_idx" ON "DailyDebrief"("status");

-- CreateIndex
CREATE INDEX "DailyDebrief_partnerId_idx" ON "DailyDebrief"("partnerId");

-- CreateIndex
CREATE INDEX "DailyDebriefRecipient_recipientUserId_readAt_idx" ON "DailyDebriefRecipient"("recipientUserId", "readAt");

-- CreateIndex
CREATE INDEX "DailyDebriefRecipient_debriefId_idx" ON "DailyDebriefRecipient"("debriefId");

-- CreateIndex
CREATE INDEX "FundRequest_status_idx" ON "FundRequest"("status");

-- CreateIndex
CREATE INDEX "FundRequest_fy_period_idx" ON "FundRequest"("fy", "period");

-- CreateIndex
CREATE INDEX "FundRequest_submittedByUserId_idx" ON "FundRequest"("submittedByUserId");

-- CreateIndex
CREATE INDEX "LeadershipDecisionInsight_fy_decisionType_idx" ON "LeadershipDecisionInsight"("fy", "decisionType");

-- CreateIndex
CREATE INDEX "LeadershipDecisionInsight_scopeType_scopeId_idx" ON "LeadershipDecisionInsight"("scopeType", "scopeId");

-- CreateIndex
CREATE INDEX "LeadershipDecisionInsight_status_idx" ON "LeadershipDecisionInsight"("status");

-- CreateIndex
CREATE INDEX "LeadershipDecisionInsight_riskLevel_idx" ON "LeadershipDecisionInsight"("riskLevel");

-- CreateIndex
CREATE INDEX "LeadershipDecisionInsight_confidenceLevel_idx" ON "LeadershipDecisionInsight"("confidenceLevel");

-- CreateIndex
CREATE INDEX "DecisionEvidencePoint_insightId_idx" ON "DecisionEvidencePoint"("insightId");

-- CreateIndex
CREATE INDEX "DecisionNote_insightId_idx" ON "DecisionNote"("insightId");

-- CreateIndex
CREATE INDEX "StaffContextProfile_fy_idx" ON "StaffContextProfile"("fy");

-- CreateIndex
CREATE UNIQUE INDEX "StaffContextProfile_staffId_fy_quarter_key" ON "StaffContextProfile"("staffId", "fy", "quarter");

-- CreateIndex
CREATE INDEX "PartnerPerformanceProfile_fy_idx" ON "PartnerPerformanceProfile"("fy");

-- CreateIndex
CREATE UNIQUE INDEX "PartnerPerformanceProfile_partnerId_fy_quarter_key" ON "PartnerPerformanceProfile"("partnerId", "fy", "quarter");

-- CreateIndex
CREATE INDEX "RecruitmentReadinessProfile_fy_idx" ON "RecruitmentReadinessProfile"("fy");

-- CreateIndex
CREATE UNIQUE INDEX "RecruitmentReadinessProfile_scopeType_scopeId_fy_quarter_key" ON "RecruitmentReadinessProfile"("scopeType", "scopeId", "fy", "quarter");

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

-- AddForeignKey
ALTER TABLE "RolePermission" ADD CONSTRAINT "RolePermission_permissionId_fkey" FOREIGN KEY ("permissionId") REFERENCES "Permission"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaffProfile" ADD CONSTRAINT "StaffProfile_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaffProfile" ADD CONSTRAINT "StaffProfile_primaryDistrictId_fkey" FOREIGN KEY ("primaryDistrictId") REFERENCES "District"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Leave" ADD CONSTRAINT "Leave_staffProfileId_fkey" FOREIGN KEY ("staffProfileId") REFERENCES "StaffProfile"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaffSupervisorAssignment" ADD CONSTRAINT "StaffSupervisorAssignment_superviseeId_fkey" FOREIGN KEY ("superviseeId") REFERENCES "StaffProfile"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaffSupervisorAssignment" ADD CONSTRAINT "StaffSupervisorAssignment_supervisorId_fkey" FOREIGN KEY ("supervisorId") REFERENCES "StaffProfile"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaffGeographyAssignment" ADD CONSTRAINT "StaffGeographyAssignment_staffId_fkey" FOREIGN KEY ("staffId") REFERENCES "StaffProfile"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaffGeographyAssignment" ADD CONSTRAINT "StaffGeographyAssignment_regionId_fkey" FOREIGN KEY ("regionId") REFERENCES "Region"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaffGeographyAssignment" ADD CONSTRAINT "StaffGeographyAssignment_districtId_fkey" FOREIGN KEY ("districtId") REFERENCES "District"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaffSchoolAssignment" ADD CONSTRAINT "StaffSchoolAssignment_staffId_fkey" FOREIGN KEY ("staffId") REFERENCES "StaffProfile"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaffSchoolAssignment" ADD CONSTRAINT "StaffSchoolAssignment_schoolId_fkey" FOREIGN KEY ("schoolId") REFERENCES "School"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaffSupportCapacity" ADD CONSTRAINT "StaffSupportCapacity_staffId_fkey" FOREIGN KEY ("staffId") REFERENCES "StaffProfile"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaffTargetProfile" ADD CONSTRAINT "StaffTargetProfile_staffId_fkey" FOREIGN KEY ("staffId") REFERENCES "StaffProfile"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SubRegion" ADD CONSTRAINT "SubRegion_regionId_fkey" FOREIGN KEY ("regionId") REFERENCES "Region"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "District" ADD CONSTRAINT "District_regionId_fkey" FOREIGN KEY ("regionId") REFERENCES "Region"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "District" ADD CONSTRAINT "District_subRegionId_fkey" FOREIGN KEY ("subRegionId") REFERENCES "SubRegion"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "County" ADD CONSTRAINT "County_districtId_fkey" FOREIGN KEY ("districtId") REFERENCES "District"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SubCounty" ADD CONSTRAINT "SubCounty_districtId_fkey" FOREIGN KEY ("districtId") REFERENCES "District"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SubCounty" ADD CONSTRAINT "SubCounty_countyId_fkey" FOREIGN KEY ("countyId") REFERENCES "County"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Parish" ADD CONSTRAINT "Parish_subCountyId_fkey" FOREIGN KEY ("subCountyId") REFERENCES "SubCounty"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Village" ADD CONSTRAINT "Village_parishId_fkey" FOREIGN KEY ("parishId") REFERENCES "Parish"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "School" ADD CONSTRAINT "School_regionId_fkey" FOREIGN KEY ("regionId") REFERENCES "Region"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "School" ADD CONSTRAINT "School_districtId_fkey" FOREIGN KEY ("districtId") REFERENCES "District"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "School" ADD CONSTRAINT "School_subCountyId_fkey" FOREIGN KEY ("subCountyId") REFERENCES "SubCounty"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "School" ADD CONSTRAINT "School_parishId_fkey" FOREIGN KEY ("parishId") REFERENCES "Parish"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "School" ADD CONSTRAINT "School_accountOwnerId_fkey" FOREIGN KEY ("accountOwnerId") REFERENCES "StaffProfile"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "School" ADD CONSTRAINT "School_clusterId_fkey" FOREIGN KEY ("clusterId") REFERENCES "Cluster"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "School" ADD CONSTRAINT "School_uploadBatchId_fkey" FOREIGN KEY ("uploadBatchId") REFERENCES "UploadBatch"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SchoolAccountOwnerUploadMap" ADD CONSTRAINT "SchoolAccountOwnerUploadMap_uploadBatchId_fkey" FOREIGN KEY ("uploadBatchId") REFERENCES "UploadBatch"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SchoolDuplicateCandidate" ADD CONSTRAINT "SchoolDuplicateCandidate_schoolId_fkey" FOREIGN KEY ("schoolId") REFERENCES "School"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SchoolDuplicateCandidate" ADD CONSTRAINT "SchoolDuplicateCandidate_candidateId_fkey" FOREIGN KEY ("candidateId") REFERENCES "School"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Cluster" ADD CONSTRAINT "Cluster_regionId_fkey" FOREIGN KEY ("regionId") REFERENCES "Region"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Cluster" ADD CONSTRAINT "Cluster_districtId_fkey" FOREIGN KEY ("districtId") REFERENCES "District"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Cluster" ADD CONSTRAINT "Cluster_subCountyId_fkey" FOREIGN KEY ("subCountyId") REFERENCES "SubCounty"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ClusterSubCounty" ADD CONSTRAINT "ClusterSubCounty_clusterId_fkey" FOREIGN KEY ("clusterId") REFERENCES "Cluster"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ClusterSubCounty" ADD CONSTRAINT "ClusterSubCounty_subCountyId_fkey" FOREIGN KEY ("subCountyId") REFERENCES "SubCounty"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SchoolClusterAssignment" ADD CONSTRAINT "SchoolClusterAssignment_schoolId_fkey" FOREIGN KEY ("schoolId") REFERENCES "School"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SchoolClusterAssignment" ADD CONSTRAINT "SchoolClusterAssignment_clusterId_fkey" FOREIGN KEY ("clusterId") REFERENCES "Cluster"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SsaRecord" ADD CONSTRAINT "SsaRecord_schoolId_fkey" FOREIGN KEY ("schoolId") REFERENCES "School"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SsaScore" ADD CONSTRAINT "SsaScore_ssaRecordId_fkey" FOREIGN KEY ("ssaRecordId") REFERENCES "SsaRecord"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SchoolEnrollmentHistory" ADD CONSTRAINT "SchoolEnrollmentHistory_schoolId_fkey" FOREIGN KEY ("schoolId") REFERENCES "School"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Activity" ADD CONSTRAINT "Activity_schoolId_fkey" FOREIGN KEY ("schoolId") REFERENCES "School"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Activity" ADD CONSTRAINT "Activity_clusterId_fkey" FOREIGN KEY ("clusterId") REFERENCES "Cluster"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Activity" ADD CONSTRAINT "Activity_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Activity" ADD CONSTRAINT "Activity_responsibleStaffId_fkey" FOREIGN KEY ("responsibleStaffId") REFERENCES "StaffProfile"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Activity" ADD CONSTRAINT "Activity_monitoredByStaffId_fkey" FOREIGN KEY ("monitoredByStaffId") REFERENCES "StaffProfile"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Activity" ADD CONSTRAINT "Activity_assignedPartnerId_fkey" FOREIGN KEY ("assignedPartnerId") REFERENCES "Partner"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ActivityScheduleCostLine" ADD CONSTRAINT "ActivityScheduleCostLine_activityId_fkey" FOREIGN KEY ("activityId") REFERENCES "Activity"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "EvidenceRecord" ADD CONSTRAINT "EvidenceRecord_activityId_fkey" FOREIGN KEY ("activityId") REFERENCES "Activity"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ActivityCompletionVerification" ADD CONSTRAINT "ActivityCompletionVerification_activityId_fkey" FOREIGN KEY ("activityId") REFERENCES "Activity"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PaymentRequest" ADD CONSTRAINT "PaymentRequest_activityId_fkey" FOREIGN KEY ("activityId") REFERENCES "Activity"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PaymentActionLog" ADD CONSTRAINT "PaymentActionLog_paymentRequestId_fkey" FOREIGN KEY ("paymentRequestId") REFERENCES "PaymentRequest"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PaymentDisbursement" ADD CONSTRAINT "PaymentDisbursement_paymentRequestId_fkey" FOREIGN KEY ("paymentRequestId") REFERENCES "PaymentRequest"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "MonthlyPlanActivity" ADD CONSTRAINT "MonthlyPlanActivity_monthlyPlanId_fkey" FOREIGN KEY ("monthlyPlanId") REFERENCES "MonthlyPlan"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CoreActivitySlot" ADD CONSTRAINT "CoreActivitySlot_corePlanId_fkey" FOREIGN KEY ("corePlanId") REFERENCES "CorePlan"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CoreSchoolProfile" ADD CONSTRAINT "CoreSchoolProfile_corePlanId_fkey" FOREIGN KEY ("corePlanId") REFERENCES "CorePlan"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CoreSchoolOnboarding" ADD CONSTRAINT "CoreSchoolOnboarding_corePlanId_fkey" FOREIGN KEY ("corePlanId") REFERENCES "CorePlan"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AnnualPlanActivity" ADD CONSTRAINT "AnnualPlanActivity_annualPlanId_fkey" FOREIGN KEY ("annualPlanId") REFERENCES "AnnualPlan"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ActivityBudgetLine" ADD CONSTRAINT "ActivityBudgetLine_annualPlanActivityId_fkey" FOREIGN KEY ("annualPlanActivityId") REFERENCES "AnnualPlanActivity"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BudgetVersion" ADD CONSTRAINT "BudgetVersion_annualPlanId_fkey" FOREIGN KEY ("annualPlanId") REFERENCES "AnnualPlan"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "BudgetApproval" ADD CONSTRAINT "BudgetApproval_budgetVersionId_fkey" FOREIGN KEY ("budgetVersionId") REFERENCES "BudgetVersion"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProjectSchoolAssignment" ADD CONSTRAINT "ProjectSchoolAssignment_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProjectSchoolAssignment" ADD CONSTRAINT "ProjectSchoolAssignment_schoolId_fkey" FOREIGN KEY ("schoolId") REFERENCES "School"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProjectPartnerAssignment" ADD CONSTRAINT "ProjectPartnerAssignment_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProjectPartnerAssignment" ADD CONSTRAINT "ProjectPartnerAssignment_partnerId_fkey" FOREIGN KEY ("partnerId") REFERENCES "Partner"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ProjectImpactSnapshot" ADD CONSTRAINT "ProjectImpactSnapshot_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES "Project"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Partner" ADD CONSTRAINT "Partner_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Message" ADD CONSTRAINT "Message_threadId_fkey" FOREIGN KEY ("threadId") REFERENCES "MessageThread"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Message" ADD CONSTRAINT "Message_senderId_fkey" FOREIGN KEY ("senderId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Notification" ADD CONSTRAINT "Notification_recipientId_fkey" FOREIGN KEY ("recipientId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "CommandCenterAlertDismissal" ADD CONSTRAINT "CommandCenterAlertDismissal_alertId_fkey" FOREIGN KEY ("alertId") REFERENCES "CommandCenterAlert"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AuditLog" ADD CONSTRAINT "AuditLog_actorId_fkey" FOREIGN KEY ("actorId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DailyDebriefRecipient" ADD CONSTRAINT "DailyDebriefRecipient_debriefId_fkey" FOREIGN KEY ("debriefId") REFERENCES "DailyDebrief"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DecisionEvidencePoint" ADD CONSTRAINT "DecisionEvidencePoint_insightId_fkey" FOREIGN KEY ("insightId") REFERENCES "LeadershipDecisionInsight"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "DecisionNote" ADD CONSTRAINT "DecisionNote_insightId_fkey" FOREIGN KEY ("insightId") REFERENCES "LeadershipDecisionInsight"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "StaffContextProfile" ADD CONSTRAINT "StaffContextProfile_staffId_fkey" FOREIGN KEY ("staffId") REFERENCES "StaffProfile"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PartnerPerformanceProfile" ADD CONSTRAINT "PartnerPerformanceProfile_partnerId_fkey" FOREIGN KEY ("partnerId") REFERENCES "Partner"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "FinanceDecisionNote" ADD CONSTRAINT "FinanceDecisionNote_insightId_fkey" FOREIGN KEY ("insightId") REFERENCES "BudgetIntelligenceInsight"("id") ON DELETE CASCADE ON UPDATE CASCADE;

