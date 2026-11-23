'use server';

import { toJson } from '@bufbuild/protobuf';

import {
  GetDrawerOptionsResponseSchema,
  GetDrawerResponseSchema,
  PageDrawerService,
  PageDrawerSchema,
  SchoolDrawerService,
} from '@/gen/edify/screens/v1/drawer_pb';
import { asReader } from '@/lib/auth';
import { isDrawerPath, safeRedirect, schoolDrawerOf } from '@/lib/drawerLogic';
import type { DrawerJson, DrawerOptionJson } from '@/lib/drawerLogic';
import { gatewayClient, isNotFound, isUnavailable, messageOf } from '@/lib/gateway';

export interface DrawerLoad {
  readonly drawer?: DrawerJson;
  /** Why the drawer cannot open; the reader is told, nothing has been written. */
  readonly refusal?: string;
  /** The drawer is still the existing web's (Go has no form for it here). */
  readonly notHere?: boolean;
}

export interface DrawerSaved {
  readonly saved: boolean;
  readonly message: string;
  readonly redirect: string;
  readonly error: string;
  readonly drawer?: DrawerJson;
}

/** A drawer's form, from the gateway, which decides who may open it. */
export async function loadDrawer(path: string): Promise<DrawerLoad> {
  if (!isDrawerPath(path)) return { refusal: 'This action cannot be opened here.' };
  const school = schoolDrawerOf(path);
  return asReader(async (token) => {
    try {
      if (school) {
        const answer = await gatewayClient(SchoolDrawerService, token).getSchoolDrawer(school);
        return answer.drawer ? { drawer: toJson(PageDrawerSchema, answer.drawer) as DrawerJson } : { notHere: true };
      }
      const answer = await gatewayClient(PageDrawerService, token).getDrawer({ path });
      const json = toJson(GetDrawerResponseSchema, answer) as { drawer?: DrawerJson; refusal?: string };
      if (json.drawer) return { drawer: json.drawer };
      return { refusal: json.refusal || 'This action cannot be opened right now.' };
    } catch (error) {
      // No form for it here: the existing web's page, where there is one.
      if (isUnavailable(error) || isNotFound(error)) return { notHere: true };
      return { refusal: messageOf(error, 'This action could not be opened. Please try again.') };
    }
  });
}

/** Saves a drawer through the gateway, which applies every rule and audit. */
export async function submitDrawer(path: string, values: Readonly<Record<string, string>>): Promise<DrawerSaved> {
  if (!isDrawerPath(path)) return { saved: false, message: '', redirect: '', error: 'This action cannot be saved here.' };
  const school = schoolDrawerOf(path);
  return asReader(async (token) => {
    try {
      const answer = school
        ? await gatewayClient(SchoolDrawerService, token).saveSchoolDrawer({ ...school, values: { ...values } })
        : await gatewayClient(PageDrawerService, token).saveDrawer({ path, values: { ...values } });
      return {
        saved: answer.saved,
        message: answer.message,
        redirect: safeRedirect(answer.redirect),
        error: answer.error,
        drawer: answer.drawer ? (toJson(PageDrawerSchema, answer.drawer) as DrawerJson) : undefined,
      };
    } catch (error) {
      return { saved: false, message: '', redirect: '', error: messageOf(error, 'This could not be saved. Nothing was changed.') };
    }
  });
}

/** The choices a field reloads when another changes. */
export async function loadDrawerOptions(source: string, name: string, value: string): Promise<readonly DrawerOptionJson[]> {
  return asReader(async (token) => {
    const answer = await gatewayClient(SchoolDrawerService, token).getDrawerOptions({ source, name, value });
    return ((toJson(GetDrawerOptionsResponseSchema, answer) as { options?: DrawerOptionJson[] }).options ?? []);
  });
}
