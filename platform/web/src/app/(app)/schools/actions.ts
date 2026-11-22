'use server';

import { revalidatePath } from 'next/cache';

import { SchoolActionService } from '@/gen/edify/screens/v1/school_actions_pb';
import { asReader } from '@/lib/auth';
import { gatewayClient, messageOf } from '@/lib/gateway';

export interface BulkSchoolActionResult {
  readonly ok: boolean;
  readonly message: string;
  readonly warnings: readonly string[];
}

export async function bulkAssignClusterAction(input: {
  schoolIds: readonly string[];
  clusterId: string;
}): Promise<BulkSchoolActionResult> {
  if (!input.schoolIds.length || !input.clusterId.trim()) {
    return { ok: false, message: 'Select at least one school and enter a cluster ID.', warnings: [] };
  }
  return asReader(async (token) => {
    try {
      const resp = await gatewayClient(SchoolActionService, token).bulkAssignCluster({
        schoolIds: [...input.schoolIds],
        clusterId: input.clusterId.trim(),
      });
      const res = resp.result;
      if (!res?.saved && res?.error) {
        return { ok: false, message: res.error, warnings: res.warnings ?? [] };
      }
      revalidatePath('/schools');
      return {
        ok: true,
        message: res?.message || 'Schools assigned to cluster.',
        warnings: res?.warnings ?? [],
      };
    } catch (error) {
      return { ok: false, message: messageOf(error, 'Could not assign schools to cluster.'), warnings: [] };
    }
  });
}

export async function bulkAssignProjectAction(input: {
  schoolIds: readonly string[];
  projectId: string;
}): Promise<BulkSchoolActionResult> {
  if (!input.schoolIds.length || !input.projectId.trim()) {
    return { ok: false, message: 'Select at least one school and enter a project ID.', warnings: [] };
  }
  return asReader(async (token) => {
    try {
      const resp = await gatewayClient(SchoolActionService, token).bulkAssignProject({
        schoolIds: [...input.schoolIds],
        projectId: input.projectId.trim(),
      });
      const res = resp.result;
      if (!res?.saved && res?.error) {
        return { ok: false, message: res.error, warnings: res.warnings ?? [] };
      }
      revalidatePath('/schools');
      return {
        ok: true,
        message: res?.message || 'Schools enrolled in project.',
        warnings: res?.warnings ?? [],
      };
    } catch (error) {
      return { ok: false, message: messageOf(error, 'Could not enroll schools in project.'), warnings: [] };
    }
  });
}
