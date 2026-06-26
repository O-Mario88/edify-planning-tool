import { IsEnum, IsInt, IsOptional, IsString } from 'class-validator';
import { ActivityType, ClusterMeetingSlot } from '@prisma/client';

export class ScheduleSchoolVisitDto {
  @IsString() schoolId!: string;
  @IsString() fy!: string;
  @IsString() quarter!: string;
  @IsOptional() @IsInt() plannedMonth?: number;
  @IsOptional() @IsInt() plannedWeek?: number;
  @IsOptional() @IsString() scheduledDate?: string;
  @IsOptional() @IsString() responsibleStaffId?: string;
}

export class AssignSchoolVisitToPartnerDto {
  @IsString() schoolId!: string;
  @IsString() assignedPartnerId!: string;
  @IsString() fy!: string;
  @IsString() quarter!: string;
  @IsOptional() @IsInt() plannedMonth?: number;
  @IsOptional() @IsInt() plannedWeek?: number;
  @IsOptional() @IsString() responsibleStaffId?: string;
}

export class ScheduleClusterTrainingDto {
  @IsString() clusterId!: string;
  @IsEnum(ActivityType) activityType!: ActivityType;
  @IsString() fy!: string;
  @IsString() quarter!: string;
  @IsOptional() @IsString() scheduledDate?: string;
  @IsOptional() @IsInt() plannedMonth?: number;
  @IsOptional() @IsInt() plannedWeek?: number;
  @IsOptional() @IsEnum(ClusterMeetingSlot) clusterSlot?: ClusterMeetingSlot;
  @IsOptional() @IsString() assignedPartnerId?: string;
  @IsOptional() @IsString() deliveryType?: 'staff' | 'partner';
}
