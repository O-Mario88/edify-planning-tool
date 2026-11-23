'use server';

/*
 * A school's Schedule visit and Assign to Partner drawers, through Go's
 * PlanningDrawerService: who may open them, what they offer and every rule of
 * the save stay there. The school is its record id or School ID.
 */
import { toJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';

import { PlanningDrawerSchema, PlanningDrawerService } from '@/gen/edify/screens/v1/planning_drawer_pb';
import { asReader } from '@/lib/auth';
import { safeRedirect } from '@/lib/drawerLogic';
import { gatewayClient, isNotFound, isUnavailable, messageOf } from '@/lib/gateway';
import type { Capacity } from '@/lib/planningLogic';

export type PlanningKind = 'schedule' | 'assign';

export interface PlanningLoad {
  readonly drawer?: JsonValue;
  readonly refusal?: string;
  /** Go cannot answer this drawer here (the existing application is not reachable). */
  readonly notHere?: boolean;
}

export interface PlanningSaved {
  readonly saved: boolean;
  readonly message: string;
  readonly redirect: string;
  readonly error: string;
}

const isKind = (kind: string): kind is PlanningKind => kind === 'schedule' || kind === 'assign';
const isSchool = (school: string) => /^[A-Za-z0-9_-]{1,64}$/.test(school);

export async function loadPlanningDrawer(school: string, kind: string): Promise<PlanningLoad> {
  if (!isKind(kind) || !isSchool(school)) return { refusal: 'This action cannot be opened here.' };
  return asReader(async (token) => {
    try {
      const answer = await gatewayClient(PlanningDrawerService, token).getPlanningDrawer({ schoolId: school, kind });
      if (answer.drawer) return { drawer: toJson(PlanningDrawerSchema, answer.drawer) };
      return { refusal: answer.refusal || 'This action cannot be opened right now.' };
    } catch (error) {
      if (isUnavailable(error) || isNotFound(error)) return { notHere: true };
      return { refusal: messageOf(error, 'This action could not be opened. Please try again.') };
    }
  });
}

export async function savePlanningDrawer(school: string, kind: string, values: Readonly<Record<string, string>>): Promise<PlanningSaved> {
  if (!isKind(kind) || !isSchool(school)) return { saved: false, message: '', redirect: '', error: 'This action cannot be saved here.' };
  return asReader(async (token) => {
    try {
      const answer = await gatewayClient(PlanningDrawerService, token).savePlanningDrawer({ schoolId: school, kind, values: { ...values } });
      return { saved: answer.saved, message: answer.message, redirect: safeRedirect(answer.redirect), error: answer.error };
    } catch (error) {
      return { saved: false, message: '', redirect: '', error: messageOf(error, 'This could not be saved. Nothing was changed.') };
    }
  });
}

export interface TrainingCapacity extends Capacity {
  readonly ceiling?: number;
  readonly scheduled: number;
  readonly staffName: string;
  readonly fy: string;
}

/** What the officer has scheduled under this training's ceiling; nothing when it cannot be read (the save still checks). */
export async function loadTrainingCapacity(training: string, date: string, school: string): Promise<TrainingCapacity | null> {
  return asReader(async (token) => {
    try {
      const answer = await gatewayClient(PlanningDrawerService, token).getTrainingCapacity({ training, date, school });
      return {
        managed: answer.managed,
        counted: answer.counted,
        remaining: answer.remaining,
        ceiling: answer.ceiling,
        scheduled: answer.scheduled,
        staffName: answer.staffName,
        fy: answer.fy,
      };
    } catch {
      return null;
    }
  });
}
