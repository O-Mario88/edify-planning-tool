import { getCurrentUser } from "@/lib/auth";
import { todayDataForRole } from "@/lib/today-mock";
import { TodayConsole } from "./TodayConsole";

// Today's Tasks — role-scoped. The server component resolves the signed-in
// user, picks the matching day (Program Lead vs CCEO field day), and
// renders the client console with that role's data + the user's identity.
export default async function TodayPage() {
  const user = await getCurrentUser();
  const data = todayDataForRole(user.role);

  return (
    <TodayConsole
      data={data}
      userName={user.name}
      userInitials={user.initials}
    />
  );
}
