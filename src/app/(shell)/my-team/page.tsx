import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { CplTeamView } from "@/components/mobile/views/CplTeamView";
import { CplTeamDesktopView } from "@/components/mobile/desktop-variants/CplTeamDesktopView";

export default function CplTeamPage() {
  return (
    <ResponsiveDashboard
      mobile={<CplTeamView />}
      desktop={<CplTeamDesktopView />}
    />
  );
}
