import { redirect } from "next/navigation";

// My Portfolio has merged into the School Directory — one page, one universe.
// Every owned school, its targets, and every assignment (cluster, special
// project, partner) now live at /schools.
export default function PortfolioRedirect() {
  redirect("/schools");
}
