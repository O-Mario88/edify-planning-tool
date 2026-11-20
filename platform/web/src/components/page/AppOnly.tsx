/*
 * A reader whose work lives only in the Edify app (the Cluster Leader: the
 * role has no web pages by design) is told so where the web would otherwise
 * answer "not found".
 */
export function AppOnly() {
  return (
    <div className="mx-auto max-w-[1500px] px-4 pt-5 sm:px-6" data-block="app-only">
      <div className="card p-6">
        <h1 className="text-[length:var(--edify-text-title-size)] font-bold">Your work is in the Edify app</h1>
        <p className="mt-1 text-[var(--edify-text-muted)]">
          Cluster Leaders plan meetings, take attendance and send reports from the Edify app on their phone. Sign in there with this
          same account.
        </p>
      </div>
    </div>
  );
}
