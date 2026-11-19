/**
 * Home's answer from Go (HomeScreenService): the page, its queue and its
 * To-Do figures, or where the reader starts instead, or "not moved yet".
 * Shared by the Home page and the redesigned Today (177 stage D), so both
 * read Go the same way and with the reader's own token.
 */
import { notFound } from 'next/navigation';

import { IdentityService } from '@/gen/edify/identity/v1/identity_pb';
import { HomeScreenService } from '@/gen/edify/screens/v1/home_pb';
import type { GetHomeQueueResponse, GetHomeResponse, HomeFigure } from '@/gen/edify/screens/v1/home_pb';
import { asReader } from '@/lib/auth';
import { gatewayClient, isNotFound, isUnavailable } from '@/lib/gateway';
import { withRouteShortcut } from '@/lib/routePlanner';

export type HomeParts = { home: GetHomeResponse; queue: GetHomeQueueResponse; figures: HomeFigure[]; total: number | undefined };
export type HomeAnswer = { kind: 'home'; parts: HomeParts } | { kind: 'elsewhere'; url: string } | { kind: 'notMoved' };

/** Each part of Home; where the reader starts instead; or not moved yet. */
export async function askHome(): Promise<HomeAnswer> {
  return asReader(async (token): Promise<HomeAnswer> => {
    const client = gatewayClient(HomeScreenService, token);
    try {
      const [answer, session] = await Promise.all([client.getHome({}), gatewayClient(IdentityService, token).getSession({})]);
      // Quick access opens Smart Route in My Plan's place for a role that plans routes.
      const home = { ...answer, shortcuts: withRouteShortcut(answer.shortcuts, session.session?.activeRole ?? '') };
      if (home.redirectUrl) return { kind: 'elsewhere', url: home.redirectUrl };
      const queue = await client.getHomeQueue({});
      if (queue.todoFiguresLater) {
        const later = await client.getHomeTodoFigures({});
        return { kind: 'home', parts: { home, queue, figures: later.queueFigures, total: later.priorityTotal } };
      }
      return { kind: 'home', parts: { home, queue, figures: queue.queueFigures, total: queue.priorityTotal } };
    } catch (error) {
      if (isNotFound(error)) notFound();
      if (isUnavailable(error)) return { kind: 'notMoved' };
      throw error;
    }
  });
}
