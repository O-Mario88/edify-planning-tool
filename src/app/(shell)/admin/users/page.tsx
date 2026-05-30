import { Users } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { DEMO_USERS } from "@/lib/auth-public";

export default function AdminUsersIndex() {
  const users = Object.values(DEMO_USERS);

  return (
    <EntityIndex
      title="Users & Roles"
      subtitle="Manage staff accounts, role assignments, and access. Production swaps DEMO_USERS for a real directory."
      Icon={Users}
      count={users.length}
      searchPlaceholder="Search users"
    >
      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {users.map((u) => (
          <IndexRow
            key={u.email}
            href={`/admin/users/${encodeURIComponent(u.email)}`}
            Icon={Users}
            title={u.name}
            subtitle={u.email}
            meta={u.role.replace(/([A-Z])/g, " $1").trim()}
            badges={[{ label: u.role, tone: "edify" }]}
          />
        ))}
      </section>
    </EntityIndex>
  );
}
