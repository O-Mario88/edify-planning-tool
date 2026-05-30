import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { QueueView } from "@/components/mobile/views/QueueView";
import { QueueDesktopView } from "@/components/mobile/desktop-variants/QueueDesktopView";

export default function Page() {
  return (
    <ResponsiveDashboard
      mobile={<QueueView />}
      desktop={
        <>
          <QueueDesktopView />
          </>
      }
    />
  );
}
