/**
 * Silhouette d'une carte d'annonce pendant le chargement. Même gabarit que
 * ListingCard pour que la page ne saute pas quand les vraies cartes
 * arrivent.
 */
export default function ListingSkeleton() {
  return (
    <div
      className="flex gap-3 rounded-lg border border-ink-700 bg-ink-800/50 p-3"
      aria-hidden="true"
    >
      <div className="skeleton h-24 w-[68px] shrink-0" />
      <div className="flex min-w-0 flex-1 flex-col gap-2 pt-0.5">
        <div className="skeleton h-3.5 w-11/12" />
        <div className="skeleton h-3.5 w-7/12" />
        <div className="mt-1 flex gap-1.5">
          <div className="skeleton h-4 w-10" />
          <div className="skeleton h-4 w-16" />
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <div className="skeleton h-5 w-16" />
          <div className="skeleton h-4 w-14" />
        </div>
        <div className="skeleton h-3 w-9/12" />
      </div>
      <div className="skeleton h-14 w-14 shrink-0 rounded-full" />
    </div>
  );
}
