import { redirect } from 'next/navigation';

/** The first page this web app draws. */
export default function Home() {
  redirect('/schools');
}
