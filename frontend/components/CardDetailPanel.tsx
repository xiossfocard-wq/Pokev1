"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import VisuelCarte from "./VisuelCarte";
import CardListings from "@/components/CardListings";
import SuiviCarte from "@/components/SuiviCarte";
import CollectionCarte from "@/components/CollectionCarte";
import LiensVerification from "@/components/LiensVerification";
import BlocCardNexus from "@/components/BlocCardNexus";
import Raisons from "@/components/Raisons";
import { CatalogCardDetail, fetchCardDetail } from "@/lib/api";
import { formatEur, formatFourchette, formatNombre } from "@/lib/format";
import { verification } from "@/lib/verifier";

/**
 * Fiche d'une carte : visuel, prix, themes, annonces en vente, tendance 7
 * jours, et tendance de fond calculee sur l'historique qu'on constitue
 * nous-memes.
 *
 * Le parti pris important est la PROJECTION. Tant que l'historique est trop
 * court, le backend rend `prix_projete_eur = null` et ce panneau explique
 * pourquoi au lieu d'afficher un chiffre. Un prix projete sur deux releves
 * serait une invention, et une invention posee a cote de vrais prix est lue
 * comme un vrai prix.
 */

const LIBELLES_FIABILITE: Record<string, string> = {
  insuffisant: "Historique insuffisant",
  faible: "Fiabilité faible",
  moyenne: "Fiabilité moyenne",
  bonne: "Fiabilité correcte",
};

function Courbe({ points }: { points: { captured_on: string; price_eur: number }[] }) {
  if (points.length < 2) return null;

  const prix = points.map((p) => p.price_eur);
  const min = Math.min(...prix);
  const max = Math.max(...prix);
  const amplitude = max - min || 1;

  const largeur = 100;
  const hauteur = 32;
  const chemin = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * largeur;
      const y = hauteur - ((p.price_eur - min) / amplitude) * hauteur;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  const monte = prix[prix.length - 1] >= prix[0];

  return (
    <div className="mt-2">
      <svg
        viewBox={`0 0 ${largeur} ${hauteur}`}
        preserveAspectRatio="none"
        className="h-12 w-full"
        role="img"
        aria-label={`Évolution du prix sur ${points.length} relevés, de ${formatEur(min)} à ${formatEur(max)}`}
      >
        <path
          d={chemin}
          fill="none"
          stroke={monte ? "#5FBE8D" : "#E5646A"}
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="flex justify-between font-mono text-[10px] text-parchment-100/60">
        <span>{points[0].captured_on}</span>
        <span>{formatFourchette(min, max)}</span>
        <span>{points[points.length - 1].captured_on}</span>
      </div>
    </div>
  );
}

export default function CardDetailPanel({
  cardId,
  onClose,
}: {
  cardId: number;
  onClose: () => void;
}) {
  const [carte, setCarte] = useState<CatalogCardDetail | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  // La fiche affichée : celle demandée, ou une autre de ses versions choisie
  // dans le panneau même.
  const [idAffiche, setIdAffiche] = useState(cardId);
  useEffect(() => setIdAffiche(cardId), [cardId]);

  useEffect(() => {
    let annule = false;
    setCarte(null);
    setErreur(null);
    fetchCardDetail(idAffiche)
      .then((d) => !annule && setCarte(d))
      .catch((e) => !annule && setErreur(e instanceof Error ? e.message : String(e)));
    return () => {
      annule = true;
    };
  }, [idAffiche]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink-950/70" onClick={onClose}>
      <div
        className="h-full w-full max-w-md overflow-y-auto border-l border-ink-700 bg-ink-900 p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <h2 className="font-display text-lg leading-tight text-parchment-100">
            {carte?.display_name ?? "Chargement…"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fermer"
            className="shrink-0 rounded-sm border border-ink-700 px-2 py-0.5 text-xs text-parchment-100/60 hover:border-ember-500/50"
          >
            ✕
          </button>
        </div>

        {erreur && (
          <p className="rounded-sm border border-rust-500/40 bg-rust-500/10 p-2.5 text-xs text-rust-400">
            {erreur}
          </p>
        )}

        {carte && (
          <div className="flex flex-col gap-4">
            {carte.image_url && (
              <div className="relative mx-auto aspect-[63/88] w-44">
                {/* Le cadre garde sa place (63×88, le format d'une carte) :
                    un repli vide y laissait un grand trou sans explication. */}
                <VisuelCarte
                  src={carte.image_url}
                  alt={carte.display_name}
                  sizes="176px"
                  repli={() => (
                    <div className="flex h-full w-full items-center justify-center rounded-md border border-dashed border-ink-700 p-3 text-center text-[11px] text-ink-400">
                      Visuel indisponible pour l&apos;instant
                    </div>
                  )}
                />
              </div>
            )}

            <div>
              {carte.price_eur === null ? (
                // Dire ce qui manque ET pourquoi : sans cela, l'utilisateur
                // conclurait a un bug de l'application plutot qu'a une
                // donnee que la source ne publie pas.
                <>
                  <p className="font-mono text-lg italic text-parchment-100/60">
                    Prix de référence inconnu
                  </p>
                  <p className="mt-1 text-[11px] leading-relaxed text-parchment-100/60">
                    Cette carte vient de la liste officielle, qui dit quelles
                    cartes existent mais pas ce qu&apos;elles valent. Aucune
                    marge ni score d&apos;affaire n&apos;est calculé pour elle
                    tant qu&apos;un prix n&apos;est pas connu.
                  </p>
                </>
              ) : (
                <p className="font-mono text-2xl text-parchment-100">
                  {formatEur(carte.price_eur)}
                </p>
              )}
              <p className="text-xs text-parchment-100/65">{carte.trend_7d.label}</p>
              {carte.price_low_eur !== null && carte.price_high_eur !== null && (
                <p className="mt-1 text-[11px] leading-relaxed text-parchment-100/60">
                  Fourchette {formatFourchette(carte.price_low_eur, carte.price_high_eur)},
                  dérivée de la volatilité récente. Ce ne sont pas des extrêmes
                  de ventes réellement conclues : la source ne publie pas cette
                  donnée.
                </p>
              )}
              {/* Deux avis extérieurs, pour se faire le sien. */}
              <div className="mt-2 flex flex-wrap gap-2">
                <LiensVerification
                  verification={verification({
                    code: carte.card_code,
                    nom: carte.display_name,
                    indices: carte.series_name,
                    nameSlug: carte.name_slug,
                    cardId: carte.id,
                  })}
                  classeBouton="rounded-md border border-ink-700 px-2.5 py-1 text-[11px] font-medium text-parchment-100 transition-colors hover:border-ember-500 hover:text-ember-400"
                />
              </div>
            </div>

            <BlocCardNexus cardId={carte.id} cote={carte.price_eur} langue={carte.language ?? null} />

            {carte.analyse?.avis && (
              // Ce qu'un connaisseur en dirait : les mêmes règles que les idées de collection.
              <div className="rounded-md border border-ink-700 bg-ink-800/60 p-3">
                <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-400">
                  L&apos;avis de l&apos;expert
                </p>
                <Raisons raisons={carte.analyse.raisons} />
                <p className="mt-1.5 text-xs italic leading-snug text-parchment-100/80">« {carte.analyse.avis} »</p>
              </div>
            )}

            {carte.analyse?.personnage && (
              <Link
                href={`/personnages/${carte.analyse.personnage.slug}`}
                onClick={onClose}
                className="block rounded-md border border-ink-700 px-3 py-2 text-xs text-ember-400 transition-colors hover:border-ember-500/60"
              >
                Toutes les cartes de {carte.analyse.personnage.nom}, de la plus accessible à la plus rare →
              </Link>
            )}

            {carte.versions && carte.versions.length > 1 && (
              <div>
                <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-400">
                  Les versions de cette carte
                </p>
                <ul className="flex list-none flex-col gap-1 p-0">
                  {carte.versions.map((v) => (
                    <li key={v.id}>
                      <button
                        type="button"
                        onClick={() => setIdAffiche(v.id)}
                        disabled={v.actuelle}
                        aria-current={v.actuelle ? "true" : undefined}
                        className={`flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left text-xs transition-colors ${
                          v.actuelle
                            ? "border-ember-500/50 bg-ember-500/10"
                            : "border-ink-700 hover:border-ember-500/40"
                        }`}
                      >
                        <span className="relative h-10 w-7 shrink-0 overflow-hidden rounded-sm bg-ink-950">
                          <VisuelCarte src={v.image_url} alt={v.display_name} sizes="28px" repli={() => null} />
                        </span>
                        <span className="flex-1 capitalize text-parchment-100">{v.nature}</span>
                        {v.exemplaires > 0 && <span className="text-moss-400">✓ {v.exemplaires}</span>}
                        {v.suivie && <span className="text-amber-200">★</span>}
                        <span className="tabular font-mono text-parchment-100">
                          {v.price_eur !== null ? formatEur(v.price_eur) : "—"}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <SuiviCarte key={carte.id} cardId={carte.id} cote={carte.price_eur} initial={carte.suivi ?? null} />
            <CollectionCarte key={carte.id} cardId={carte.id} initial={carte.collection?.exemplaires ?? 0} />

            <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
              <dt className="text-parchment-100/60">Code</dt>
              <dd className="font-mono text-parchment-100/80">{carte.card_code ?? "—"}</dd>
              <dt className="text-parchment-100/60">Série</dt>
              <dd className="text-parchment-100/80">{carte.series_name ?? "—"}</dd>
              <dt className="text-parchment-100/60">Rareté</dt>
              <dd className="text-parchment-100/80">{carte.rarity ?? "—"}</dd>
              <dt className="text-parchment-100/60">Langue du nom</dt>
              <dd className="text-parchment-100/80">
                {carte.language === "fr"
                  ? "Français"
                  : carte.language === "en"
                    ? "Anglais"
                    : "—"}
              </dd>
            </dl>

            {/* La fiche a la place d'expliquer ce que la pastille de la
                grille ne peut que signaler. La formulation vient du
                backend, pour qu'une carte anglaise soit décrite de la même
                façon partout : décrite autrement d'un écran à l'autre, elle
                laisserait croire à deux situations différentes. */}
            {carte.language === "en" && carte.language_note && (
              <p className="rounded border border-ink-700 bg-ink-800/60 p-2.5 text-[11px] leading-relaxed text-parchment-100/65">
                {carte.language_note} Le jeu français n&apos;a commencé
                qu&apos;à la série OP09 : les séries antérieures n&apos;y
                figurent pas. La carte reste au catalogue, mais son nom et
                son visuel sont ceux de l&apos;édition anglaise.
              </p>
            )}

            {carte.themes_detail.length > 0 && (
              <div>
                <h3 className="mb-1.5 text-[11px] uppercase tracking-wide text-parchment-100/60">
                  Thèmes
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {carte.themes_detail.map((t) => (
                    <span
                      key={t.slug}
                      title={t.description}
                      className="rounded-sm border border-ink-600 bg-ink-800 px-1.5 py-0.5 text-[11px] text-parchment-100/70"
                    >
                      {t.label}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <CardListings cardId={carte.id} />

            <div className="border-t border-ink-700 pt-3">
              <h3 className="mb-1 text-[11px] uppercase tracking-wide text-parchment-100/60">
                Tendance de fond
              </h3>

              {carte.trend_history.fiabilite === "insuffisant" ? (
                <p className="text-[11px] leading-relaxed text-parchment-100/60">
                  {carte.trend_history.avertissement}
                  {carte.trend_history.points > 0 && (
                    <>
                      {" "}
                      Pour l&apos;instant : {carte.trend_history.points} relevé
                      {carte.trend_history.points > 1 ? "s" : ""} sur{" "}
                      {carte.trend_history.jours_couverts} jour
                      {carte.trend_history.jours_couverts > 1 ? "s" : ""}.
                    </>
                  )}
                </p>
              ) : (
                <>
                  <p className="text-xs text-parchment-100/80">
                    {carte.trend_history.variation_pct !== null && (
                      <>
                        {carte.trend_history.variation_pct > 0 ? "+" : ""}
                        {formatNombre(carte.trend_history.variation_pct, 1)} % sur{" "}
                        {carte.trend_history.jours_couverts} jours
                      </>
                    )}
                  </p>
                  <p className="font-mono text-[11px] text-parchment-100/60">
                    {carte.trend_history.points} relevés ·{" "}
                    {LIBELLES_FIABILITE[carte.trend_history.fiabilite]} · qualité
                    d&apos;ajustement r² = {carte.trend_history.r2?.toFixed(2)}
                  </p>
                  <Courbe points={carte.history} />
                </>
              )}
            </div>

            <div className="rounded-sm border border-ink-700 bg-ink-950 p-2.5">
              <h3 className="mb-1 text-[11px] uppercase tracking-wide text-parchment-100/60">
                Projection à {carte.projection.horizon_jours} jours
              </h3>
              {carte.projection.prix_projete_eur === null ? (
                <p className="text-[11px] leading-relaxed text-parchment-100/60">
                  Aucune projection affichée : {carte.projection.avertissement}
                </p>
              ) : (
                <>
                  <p className="font-mono text-lg text-ember-400">
                    ≈ {formatEur(carte.projection.prix_projete_eur)}
                  </p>
                  <p className="text-[11px] leading-relaxed text-parchment-100/60">
                    {carte.projection.avertissement}
                  </p>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
