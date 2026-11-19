import { redirect } from 'next/navigation';

/** The first page this web app draws: Home, every reader's own role home
 *  (owner, 2026-11-19: "Own role home"). */
export default function Home() {
  redirect('/home');
}
