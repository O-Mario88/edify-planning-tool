import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { MoreView } from "@/components/mobile/views/MoreView";
import { MoreDesktopView } from "@/components/mobile/desktop-variants/MoreDesktopView";

export default function MorePage() {
  return (
    <ResponsiveDashboard
      mobile={<MoreView />}
      desktop={<MoreDesktopView />}
    />
  );
}
