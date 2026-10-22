"use client";

import { CardFilterValues, CardSortField, CardTheme } from "@/lib/api";

/**
 * Panneau de filtres du catalogue.
 *
 * Les valeurs proposees viennent de /api/cards/filters, donc de ce qui est
 * REELLEMENT en base : proposer une rarete qu'aucune carte ne porte ne
 * servirait qu'a offrir un filtre qui ne rend rien.
 */

export interface EtatFiltres {
  q: string;
  theme: string;
  rarity: string;
  series: string;
  priceMin: string;
  priceMax: string;
  trend: "toutes" | "hausse" | "baisse";
  withImageOnly: boolean;
  withListingsOnly: boolean;
  // "" = toutes. "fr" / "en" = langue du NOM affiché sur la fiche.
  language: "" | "fr" | "en";
  sortBy: CardSortField;
  order: "asc" | "desc";
}

export const FILTRES_VIDES: EtatFiltres = {
  q: "",
  theme: "",
  rarity: "",
  series: "",
  priceMin: "",
  priceMax: "",
  trend: "toutes",
  withImageOnly: false,
  withListingsOnly: false,
  language: "",
  sortBy: "prix",
  order: "desc",
};

const classeChamp =
  "w-full rounded-sm border border-ink-700 bg-ink-950 px-2 py-1.5 text-xs text-parchment-100 focus:border-ember-500/60 focus:outline-none";

const classeEtiquette =
  "mb-1 block text-[11px] uppercase tracking-wide text-parchment-100/40";

export default function CardFilters({
  valeurs,
  filtres,
  themes,
  onChange,
  onReset,
}: {
  valeurs: CardFilterValues | null;
  filtres: EtatFiltres;
  themes: CardTheme[];
  onChange: (modif: Partial<EtatFiltres>) => void;
  onReset: () => void;
}) {
  // Les themes de SUJET et de TYPE repondent a deux besoins differents :
  // qui est sur la carte, et comment elle est imprimee. Les melanger
  // dans une seule liste rendrait le choix illisible.
  const themesSujet = themes.filter((t) => t.famille === "sujet");
  const themesType = themes.filter((t) => t.famille === "type");

  return (
    // Collant sur grand ecran : la grille fait plusieurs ecrans de haut, et
    // sans ca les filtres partaient hors de vue des la deuxieme rangee —
    // il fallait remonter tout en haut pour changer un critere.
    <aside className="flex w-full shrink-0 flex-col gap-3.5 self-start rounded-md border border-ink-700 bg-ink-900 p-3.5 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:w-64 lg:overflow-y-auto">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-sm text-parchment-100">Filtres</h2>
        <button
          type="button"
          onClick={onReset}
          className="text-[11px] text-parchment-100/45 underline-offset-2 hover:text-ember-400 hover:underline"
        >
          Tout effacer
        </button>
      </div>

      <div>
        <label className={classeEtiquette} htmlFor="filtre-q">
          Nom ou code
        </label>
        <input
          id="filtre-q"
          type="search"
          value={filtres.q}
          onChange={(e) => onChange({ q: e.target.value })}
          placeholder="Luffy, Zoro, OP01-120…"
          className={classeChamp}
        />
      </div>

      <div>
        <label className={classeEtiquette} htmlFor="filtre-theme">
          Thème
        </label>
        <select
          id="filtre-theme"
          value={filtres.theme}
          onChange={(e) => onChange({ theme: e.target.value })}
          className={classeChamp}
        >
          <option value="">Tous les thèmes</option>
          <optgroup label="Par sujet">
            {themesSujet.map((t) => (
              <option key={t.slug} value={t.slug} disabled={t.card_count === 0}>
                {t.label} ({t.card_count})
              </option>
            ))}
          </optgroup>
          <optgroup label="Par type de carte">
            {themesType.map((t) => (
              <option key={t.slug} value={t.slug} disabled={t.card_count === 0}>
                {t.label} ({t.card_count})
              </option>
            ))}
          </optgroup>
        </select>
      </div>

      <div>
        <span className={classeEtiquette}>Prix (€)</span>
        <div className="flex items-center gap-1.5">
          <input
            type="number"
            min={0}
            step="0.5"
            value={filtres.priceMin}
            onChange={(e) => onChange({ priceMin: e.target.value })}
            placeholder={valeurs?.price_min_eur?.toFixed(0) ?? "min"}
            aria-label="Prix minimum"
            className={classeChamp}
          />
          <span className="text-parchment-100/30">–</span>
          <input
            type="number"
            min={0}
            step="0.5"
            value={filtres.priceMax}
            onChange={(e) => onChange({ priceMax: e.target.value })}
            placeholder={valeurs?.price_max_eur?.toFixed(0) ?? "max"}
            aria-label="Prix maximum"
            className={classeChamp}
          />
        </div>
      </div>

      <div>
        <label className={classeEtiquette} htmlFor="filtre-rarete">
          Rareté
        </label>
        <select
          id="filtre-rarete"
          value={filtres.rarity}
          onChange={(e) => onChange({ rarity: e.target.value })}
          className={classeChamp}
        >
          <option value="">Toutes</option>
          {(valeurs?.rarities ?? []).map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className={classeEtiquette} htmlFor="filtre-langue">
          Langue du nom
        </label>
        <select
          id="filtre-langue"
          value={filtres.language}
          onChange={(e) =>
            onChange({ language: e.target.value as EtatFiltres["language"] })
          }
          className={classeChamp}
        >
          <option value="">Toutes</option>
          {/* Le compte est affiché avec chaque option : sans lui, choisir
              « Anglais » et tomber sur 3 861 cartes serait une surprise. */}
          {(valeurs?.languages ?? [])
            .filter((l) => l.code === "fr" || l.code === "en")
            .map((l) => (
              <option key={l.code} value={l.code ?? ""}>
                {l.label} ({l.count.toLocaleString("fr-FR")})
              </option>
            ))}
        </select>
      </div>

      <div>
        <label className={classeEtiquette} htmlFor="filtre-serie">
          Série
        </label>
        <select
          id="filtre-serie"
          value={filtres.series}
          onChange={(e) => onChange({ series: e.target.value })}
          className={classeChamp}
        >
          <option value="">Toutes</option>
          {(valeurs?.series ?? []).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      <div>
        <span className={classeEtiquette}>Tendance 7 jours</span>
        <div className="flex gap-1">
          {([
            ["toutes", "Toutes"],
            ["hausse", "En hausse"],
            ["baisse", "En baisse"],
          ] as const).map(([valeur, libelle]) => (
            <button
              key={valeur}
              type="button"
              onClick={() => onChange({ trend: valeur })}
              className={`flex-1 rounded-sm border px-1.5 py-1 text-[11px] transition-colors ${
                filtres.trend === valeur
                  ? "border-ember-500/60 bg-ember-500/15 text-ember-400"
                  : "border-ink-700 text-parchment-100/50 hover:border-ink-600"
              }`}
            >
              {libelle}
            </button>
          ))}
        </div>
      </div>

      <div>
        <span className={classeEtiquette}>Trier par</span>
        <div className="flex gap-1.5">
          <select
            value={filtres.sortBy}
            onChange={(e) => onChange({ sortBy: e.target.value as CardSortField })}
            aria-label="Critère de tri"
            className={classeChamp}
          >
            <option value="prix">Prix</option>
            <option value="variation">Variation 7 j</option>
            <option value="nom">Nom</option>
            <option value="maj">Mise à jour</option>
          </select>
          <button
            type="button"
            onClick={() => onChange({ order: filtres.order === "desc" ? "asc" : "desc" })}
            title={filtres.order === "desc" ? "Décroissant" : "Croissant"}
            className="shrink-0 rounded-sm border border-ink-700 px-2 text-xs text-parchment-100/60 hover:border-ember-500/50"
          >
            {filtres.order === "desc" ? "↓" : "↑"}
          </button>
        </div>
      </div>

      <label className="flex cursor-pointer items-center gap-2 text-[11px] text-parchment-100/55">
        <input
          type="checkbox"
          checked={filtres.withImageOnly}
          onChange={(e) => onChange({ withImageOnly: e.target.checked })}
          className="accent-ember-500"
        />
        Seulement les cartes avec visuel
      </label>

      <label
        className="flex cursor-pointer items-center gap-2 text-[11px] text-parchment-100/55"
        title="Les cartes pour lesquelles au moins une annonce est en vente en ce moment"
      >
        <input
          type="checkbox"
          checked={filtres.withListingsOnly}
          onChange={(e) => onChange({ withListingsOnly: e.target.checked })}
          className="accent-ember-500"
        />
        Seulement les cartes en vente
      </label>

      {valeurs && (
        <p className="border-t border-ink-700 pt-2.5 text-[11px] leading-relaxed text-parchment-100/35">
          {valeurs.total_cards.toLocaleString("fr-FR")} cartes dans le
          catalogue.{" "}
          {(() => {
            // Le détail par langue plutôt qu'un total seul : dire « 3 870
            // cartes » laisserait croire à un catalogue français complet
            // alors que la plupart portent encore leur nom anglais.
            const en = valeurs.languages?.find((l) => l.code === "en")?.count ?? 0;
            const fr = valeurs.languages?.find((l) => l.code === "fr")?.count ?? 0;
            if (!en) return null;
            return (
              <>
                {fr.toLocaleString("fr-FR")} ont été retrouvées dans la liste
                officielle française ; {en.toLocaleString("fr-FR")} portent
                encore leur nom anglais — le jeu français n&apos;a commencé
                qu&apos;à la série OP09.{" "}
              </>
            );
          })()}
          Les prix de référence viennent d&apos;une autre source et arrivent
          carte par carte.
        </p>
      )}
    </aside>
  );
}
