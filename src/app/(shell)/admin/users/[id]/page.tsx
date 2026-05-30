import { notFound } from "next/navigation";
import { Users } from "lucide-react";
import { EntityDetail, DetailFacts } from "@/components/shell/EntityDetail";
import { DEMO_USERS } from "@/lib/auth-public";

export default async function AdminUserDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const email = decodeURIComponent(id);
  const u = DEMO_USERS[email];
  if (!u) return notFound();

  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home",  href: "/dashboard" },
        { label: "Admin", href: "/admin" },
        { label: "Users", href: "/admin/users" },
        { label: u.name },
      ]}
      title={u.name}
      subtitle={u.email}
      Icon={Users}
      badge={{ tone: "edify", label: u.role }}
    >
      <DetailFacts
        rows={[
          { label: "Email",  value: u.email },
          { label: "Role",   value: u.role.replace(/([A-Z])/g, " $1").trim() },
          { label: "Status", value: "Active" },
        ]}
      />
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Permissions</h2>
        <p className="text-[11.5px] muted">
          Permissions are inherited from the user&apos;s role. To change them, edit the role assignment.
          Role changes are audited and require a second-Admin approval in production.
        </p>
      </section>
    </EntityDetail>
  );
}
