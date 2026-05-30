import { redirect } from "next/navigation";

// The platform's only landing point. Server-side redirect into the
// role-aware /dashboard entry, which then forwards to the right dashboard
// for the logged-in user (or to /login if there's no session cookie).
export default function Home() {
  redirect("/dashboard");
}
