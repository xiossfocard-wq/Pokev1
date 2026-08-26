"use client";

import type { Listing, ListingSource, SortField, SortOrder } from "@/lib/api";
import ListingCard from "./ListingCard";
import SortBar from "./SortBar";

interface ListingColumnProps {
  source: ListingSource;
  listings: Listing[];
  loading: boolean;
  sortBy: SortField;
  order: SortOrder;
  onSortChange: (sortBy: SortField, order: SortOrder) => void;
  /** Appelé quand l'utilisateur corrige une annonce (prix, mauvaise carte,
   *  masquage) : le parent met sa liste à jour sans tout recharger. */
  onListingChanged?: (updated: Listing) => void;
}

const SOURCE_LABEL: Record<ListingSource, string> = { vinted: "Vinted", ebay: "eBay" };
const SOURCE_DOT: Record<ListingSource, string> = { vinted: "bg-moss-400", ebay: "bg-ember-400" };

export default function ListingColumn({
  source,
  listings,
  loading,
  sortBy,
  order,
  onSortChange,
  onListingChanged,
}: ListingColumnProps) {
  return (
    <section className="flex-1 min-w-0">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="flex items-center gap-2 font-display text-lg text-parchment-100">
          <span className={`h-2 w-2 rounded-full ${SOURCE_DOT[source]}`} />
          {SOURCE_LABEL[source]}
          <span className="font-mono text-xs font-normal text-ink-600">
            {listings.length}
          </span>
        </h2>
        <SortBar sortBy={sortBy} order={order} onChange={onSortChange} />
      </div>

      <div className="flex flex-col gap-2">
        {loading && (
          <div className="rounded-md border border-dashed border-ink-700 p-6 text-center text-xs text-ink-600">
            Chargement…
          </div>
        )}
        {!loading && listings.length === 0 && (
          <div className="rounded-md border border-dashed border-ink-700 p-6 text-center text-xs text-ink-600">
            Aucune annonce pour l&apos;instant. Le prochain cycle de vérification
            en trouvera peut-être.
          </div>
        )}
        {listings.map((l) => (
          <ListingCard key={l.id} listing={l} onChanged={onListingChanged} />
        ))}
      </div>
    </section>
  );
}
