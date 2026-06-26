import { IsArray, IsEmail, IsEnum, IsOptional, IsString, MinLength } from 'class-validator';
import { EdifyRole } from '@prisma/client';

/** Admin creates a user — no password (they set it via the invite link). */
export class CreateUserDto {
  @IsString()
  @MinLength(1)
  name!: string;

  @IsEmail()
  email!: string;

  @IsOptional()
  @IsString()
  phone?: string;

  @IsEnum(EdifyRole)
  role!: EdifyRole;

  /** Optional: a second role the user also holds. */
  @IsOptional()
  @IsArray()
  @IsEnum(EdifyRole, { each: true })
  additionalRoles?: EdifyRole[];

  /** Optional primary district id (for staff profiles). */
  @IsOptional()
  @IsString()
  primaryDistrictId?: string;
}
