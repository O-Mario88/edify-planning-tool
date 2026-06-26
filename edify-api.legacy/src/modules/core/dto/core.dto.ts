import { Type } from 'class-transformer';
import {
  ArrayMinSize, IsArray, IsDateString, IsEnum, IsInt, IsNumber, IsOptional, IsString, Max, Min, ValidateNested,
} from 'class-validator';
import { SsaIntervention } from '@prisma/client';

class FollowUpScoreInput {
  @IsEnum(SsaIntervention)
  intervention!: SsaIntervention;

  @IsNumber()
  @Min(0)
  @Max(10)
  score!: number;
}

export class VerifyCandidateDto {
  @IsString()
  verificationId!: string;

  @IsOptional()
  @IsString()
  comments?: string;
}

export class RejectCandidateDto {
  @IsString()
  reason!: string;
}

export class OnboardCoreDto {
  @IsOptional()
  @IsString()
  reason?: string;
}

export class SlotAssignDto {
  @IsString()
  owner!: string;

  @IsOptional()
  @IsString()
  ownerName?: string;

  @IsOptional()
  @IsString()
  partnerId?: string;

  @IsOptional()
  @IsString()
  monthLabel?: string;

  @IsOptional()
  @IsInt()
  week?: number;
}

export class SlotScheduleDto {
  @IsString()
  monthLabel!: string;

  @IsInt()
  week!: number;
}

export class SlotEvidenceDto {
  @IsString()
  evidenceUri!: string;

  @IsOptional()
  @IsString()
  notes?: string;
}

export class SlotReturnDto {
  @IsString()
  reason!: string;
}

export class SlotCompleteDto {
  @IsString()
  salesforceId!: string;

  @IsOptional()
  @IsInt()
  teachers?: number;

  @IsOptional()
  @IsInt()
  leaders?: number;

  @IsOptional()
  @IsInt()
  participants?: number;
}

export class ScheduleFollowUpDto {
  @IsString()
  assignee!: string;

  @IsString()
  monthLabel!: string;

  @IsOptional()
  @IsInt()
  week?: number;
}

export class UploadFollowUpSsaDto {
  @IsOptional()
  @IsDateString()
  dateOfSsa?: string;

  @IsArray()
  @ArrayMinSize(8)
  @ValidateNested({ each: true })
  @Type(() => FollowUpScoreInput)
  scores!: FollowUpScoreInput[];
}
