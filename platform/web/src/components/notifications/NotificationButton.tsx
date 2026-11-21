import { revalidatePath } from 'next/cache';
import type { ReactNode } from 'react';
import { NotificationCenterService, NotificationStatusAction } from '@/gen/edify/screens/v1/notification_center_pb';
import { gatewayClient } from '@/lib/gateway';
import { asReader } from '@/lib/auth';

export function NotificationButton({ action, id = '', children, className }: {
  action: NotificationStatusAction;
  id?: string;
  children: ReactNode;
  className: string;
}) {
  async function submit() {
    'use server';
    await asReader((token) => gatewayClient(NotificationCenterService, token).updateNotificationStatus({
      action, notificationId: id,
    }));
    revalidatePath('/notifications');
  }
  return <form action={submit}><button type="submit" className={className}>{children}</button></form>;
}
