import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { RouteView } from "@/components/mobile/views/RouteView";
import { RouteDesktopView } from "@/components/planning/RouteDesktopView";

export default function RoutePage() {
  return (
    <ResponsiveDashboard
      mobile={<RouteView />}
      desktop={
        <>
          <RouteDesktopView />
          </>
      }
    />
  );
}
