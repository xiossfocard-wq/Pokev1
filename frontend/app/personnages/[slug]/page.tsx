"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import CardDetailPanel from "@/components/CardDetailPanel";
import { Annonce } from "@/components/CardListings";
import TuileCarte from "@/components/TuileCarte";
import VisuelCarte from "@/components/VisuelCarte";
import {
  chasserPersonnage,
  enregistrerGouts,
  fetchGouts,
  fetchPersonnage,
  type AnnoncePersonnage,
  type PagePersonnage,
} from "@/lib/api";
import { formatEur } from "@/lib/format";
import { rechargerListe, useCartesSuivies } from "@/lib/suivi";

/**
 * La page d'un personnage apprécié : toutes ses cartes, de la plus
 * accessible à la plus rare, rangées par palier de prix, et ce qu'un
 * connaisseur conseillerait pour en faire une collection.
 */
export default function PagePersonnageRoute() {
  const { slug } = useParams<{ slug: string }>();
  const [page, setPage] = useState<PagePersonnage | null>(null);
  const [introuvable, setIntrouvable] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [toutesLangues, setToutesLangues] = useState(false);
  const [carteOuverte, setCarteOuverte] = useState<number | null>(null);

  const charger = useCallback(() => {
    setErreur(null);
    fetchPersonnage(slug, toutesLangues)
      .then((p) => {
        setPage(p);
        setIntrouvable(false);
      })
      .catch((e) => {
        const message = e instanceof Error ? e.message : String(e);
        if (message.startsWith("Erreur API 404")) setIntrouvable(true);
        else setErreur(message);
      });
  }, [slug, toutesLangues]);
  // D'un personnage à l'autre (lien d'une fiche), on n'affiche pas l'ancien.
  useEffect(() => setPage(null), [slug]);
  useEffect(charger, [charger]);

  // La fiche fermée, la page se recharge : la carte a pu être ajoutée à la
  // collection ou à Ma liste depuis la fiche.
  function fermerLaFiche() {
    setCarteOuverte(null);
    charger();
  }

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-ink-800 bg-ink-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5">
          <Link href="/" className="font-display text-lg leading-none text-parchment-100">
            Radar
          </Link>
          <span className="text-ink-400">/</span>
          <Link href="/personnages" className="text-sm text-ink-400 hover:text-parchment-100">
            Personnages
          </Link>
          {page && (
            <>
              <span className="hidden text-ink-400 sm:inline">/</span>
              <span className="hidden truncate text-sm text-parchment-100 sm:inline">{page.nom}</span>
            </>
          )}
          <div className="ml-auto flex shrink-0 gap-1.5">
            <Link
              href="/suivi"
              className="rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500"
            >
              ★ Ma liste
            </Link>
            <Link
              href="/collection"
              className="rounded-md border border-ink-700 px-2.5 py-1.5 text-xs text-parchment-100 transition-colors hover:border-ember-500"
            >
              Collection
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 pb-16 pt-6">
        {introuvable && (
          <div className="py-16 text-center">
            <p className="font-display text-xl text-parchment-100">Pas de page pour ce personnage</p>
            <p className="mt-2 text-sm text-ink-400">
              Seuls les icônes de la série et les personnages les plus recherchés ont leur page.
            </p>
            <Link href="/personnages" className="mt-4 inline-block text-sm text-ember-400 underline underline-offset-2">
              Voir les personnages
            </Link>
          </div>
        )}

        {erreur && (
          <div className="rounded-md border border-rust-500/40 bg-rust-500/10 px-3 py-2 text-xs text-rust-400">
            Impossible de charger la page. [{erreur}]
          </div>
        )}

        {!page && !introuvable && !erreur && (
          <div className="space-y-4">
            <div className="skeleton h-28" />
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-5">
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="skeleton aspect-[63/110]" />
              ))}
            </div>
          </div>
        )}

        {page && !introuvable && (
          <>
            <EnTete page={page} toutesLangues={toutesLangues} onChange={charger} />

            <label className="mt-4 flex items-center gap-2 text-xs text-ink-400">
              <input
                type="checkbox"
                checked={toutesLangues}
                onChange={(e) => setToutesLangues(e.target.checked)}
                className="accent-ember-500"
              />
              Inclure les séries sans version française
            </label>

            {page.cartes === 0 && (
              <p className="mt-6 text-sm text-ink-400">
                Aucune de ses cartes n&apos;est encore au catalogue
                {toutesLangues ? "" : " en français — coche la case ci-dessus pour voir les autres séries"}.
              </p>
            )}

            {page.conseils.length > 0 && (
              <section className="mt-8">
                <h2 className="font-display text-xl text-parchment-100">Les conseils de l&apos;expert</h2>
                <ul className="mt-3 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2 lg:grid-cols-4">
                  {page.conseils.map((c) => (
                    <li key={c.cle}>
                      <button
                        type="button"
                        onClick={() => setCarteOuverte(c.carte.id)}
                        className="flex h-full w-full gap-3 rounded-lg border border-amber-300/25 bg-ink-800/60 p-3 text-left transition-colors hover:border-amber-300/60"
                      >
                        <div className="relative h-20 w-14 shrink-0 overflow-hidden rounded-sm bg-ink-950">
                          <VisuelCarte src={c.carte.image_url} alt={c.carte.display_name} sizes="56px" repli={() => null} />
                        </div>
                        <div className="min-w-0">
                          <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-amber-200">{c.titre}</p>
                          <p className="mt-0.5 text-xs font-medium capitalize text-parchment-100">
                            {c.carte.version} · {c.carte.card_code}
                          </p>
                          <p className="mt-1 text-[11px] leading-snug text-ink-400">{c.texte}</p>
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {page.cartes > 0 && <EnVente annonces={page.annonces} onOuvrir={setCarteOuverte} />}

            {page.paliers.map((palier) => (
              <section key={palier.cle} className="mt-10">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                  <h2 className="font-display text-xl text-parchment-100">{palier.titre}</h2>
                  <p className="text-xs text-ink-400">
                    {palier.explication} · {palier.cartes.length} carte{palier.cartes.length > 1 ? "s" : ""}
                  </p>
                </div>
                <ul className="mt-3 grid list-none grid-cols-2 gap-3 p-0 sm:grid-cols-4 lg:grid-cols-5">
                  {palier.cartes.map((carte) => (
                    <TuileCarte key={carte.id} carte={carte} onOuvrir={setCarteOuverte} />
                  ))}
                </ul>
              </section>
            ))}
          </>
        )}
      </main>

      {carteOuverte !== null && <CardDetailPanel cardId={carteOuverte} onClose={fermerLaFiche} />}
    </>
  );
}

/**
 * Le personnage en bref : combien de cartes, de belles versions, de quel à
 * quel prix, où en est sa collection — et le cœur pour l'ajouter à ses goûts
 * (les idées de collection s'y adaptent).
 */
function EnTete({
  page,
  toutesLangues,
  onChange,
}: {
  page: PagePersonnage;
  toutesLangues: boolean;
  onChange: () => void;
}) {
  const [occupe, setOccupe] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const part = page.belles > 0 ? Math.round((page.belles_possedees / page.belles) * 100) : 0;

  async function basculerAime() {
    setOccupe(true);
    setErreur(null);
    try {
      const { gouts } = await fetchGouts();
      const personnages = page.aime
        ? gouts.personnages.filter((n) => n !== page.nom)
        : [...gouts.personnages.filter((n) => n !== page.nom), page.nom];
      await enregistrerGouts({ ...gouts, personnages });
      onChange();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : String(e));
    } finally {
      setOccupe(false);
    }
  }

  return (
    <section className="rounded-lg border border-ink-700 bg-ink-900/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-amber-200">
            {page.calibre === "icone" ? "Une icône de la série" : "Très recherché"}
          </p>
          <h1 className="mt-0.5 font-display text-3xl text-parchment-100">{page.nom}</h1>
          <p className="mt-1 text-xs text-ink-400">
            {page.cartes} carte{page.cartes > 1 ? "s" : ""} · {page.belles} belle{page.belles > 1 ? "s" : ""} version
            {page.belles > 1 ? "s" : ""}
            {page.prix_min !== null && page.prix_max !== null && (
              <>
                {" "}
                · de <span className="tabular font-mono text-parchment-100">{formatEur(page.prix_min)}</span> à{" "}
                <span className="tabular font-mono text-parchment-100">{formatEur(page.prix_max)}</span>
              </>
            )}
          </p>
        </div>
        <button
          type="button"
          onClick={basculerAime}
          disabled={occupe}
          aria-pressed={page.aime}
          className={`shrink-0 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-60 ${
            page.aime
              ? "border-rose-400/50 bg-rose-400/10 text-rose-300"
              : "border-ink-600 text-parchment-100 hover:border-rose-400/60"
          }`}
          title={
            page.aime
              ? "Le retirer de tes goûts"
              : "L'ajouter à tes goûts : les idées de collection le mettront en avant et suivront ta collection"
          }
        >
          {page.aime ? "♥ Dans tes goûts" : "♡ Ajouter à mes goûts"}
        </button>
      </div>

      {page.belles > 0 && (
        <div className="mt-4 max-w-md">
          <div className="flex items-baseline justify-between text-[11px] text-ink-400">
            <span>Ta collection de ses belles versions</span>
            <span className="tabular font-mono text-parchment-100">
              {page.belles_possedees} / {page.belles}
            </span>
          </div>
          <div
            className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-700"
            role="progressbar"
            aria-valuenow={page.belles_possedees}
            aria-valuemin={0}
            aria-valuemax={page.belles}
            aria-label={`${page.belles_possedees} sur ${page.belles} belles versions`}
          >
            <div className="h-full rounded-full bg-amber-300/80" style={{ width: `${part}%` }} />
          </div>
          {page.possedees > page.belles_possedees && (
            <p className="mt-1 text-[11px] text-ink-400">
              Et {page.possedees - page.belles_possedees} autre{page.possedees - page.belles_possedees > 1 ? "s" : ""}{" "}
              de ses cartes.
            </p>
          )}
        </div>
      )}
      {erreur && <p className="mt-2 text-xs text-rust-400">Goûts non enregistrés. [{erreur}]</p>}
      {page.belles > page.belles_possedees && (
        <Chasse page={page} toutesLangues={toutesLangues} onChassees={onChange} />
      )}
    </section>
  );
}

const BUDGETS_CHASSE = [10, 20, 50, 100];

/**
 * Chasser ses belles versions : toutes celles qui manquent, dans un budget,
 * ajoutées d'un coup à Ma liste avec leur cote comme budget. La chasse
 * Vinted les cherche ensuite et prévient quand une annonce passe dessous.
 */
function Chasse({
  page,
  toutesLangues,
  onChassees,
}: {
  page: PagePersonnage;
  toutesLangues: boolean;
  onChassees: () => void;
}) {
  const { budgets } = useCartesSuivies();
  const [budget, setBudget] = useState(20);
  const [occupe, setOccupe] = useState(false);
  const [resultat, setResultat] = useState<{ ajoutees: number; cout: number } | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const manquantes = page.paliers
    .flatMap((p) => p.cartes)
    .filter((c) => c.belle && c.exemplaires === 0 && c.price_eur);
  const aSuivre = manquantes.filter((c) => !c.suivie && !budgets.has(c.id) && (c.price_eur ?? 0) <= budget);
  const dejaSuivies = manquantes.filter((c) => c.suivie || budgets.has(c.id)).length;
  const auDela = manquantes.filter((c) => !c.suivie && !budgets.has(c.id) && (c.price_eur ?? 0) > budget);
  const cout = aSuivre.reduce((t, c) => t + (c.price_eur ?? 0), 0);

  async function chasser() {
    setOccupe(true);
    setErreur(null);
    try {
      setResultat(await chasserPersonnage(page.slug, budget, toutesLangues));
      await rechargerListe();
      onChassees();
    } catch (e) {
      setErreur(e instanceof Error ? e.message : String(e));
    } finally {
      setOccupe(false);
    }
  }

  return (
    <div className="mt-4 rounded-md border border-amber-300/25 bg-ink-800/50 p-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-amber-200">Chasser ses belles versions</p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="Budget par carte">
        <span className="mr-0.5 text-[11px] text-ink-400">Jusqu&apos;à</span>
        {BUDGETS_CHASSE.map((b) => (
          <button
            key={b}
            type="button"
            aria-pressed={b === budget}
            onClick={() => {
              setBudget(b);
              setResultat(null);
            }}
            className={`rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
              b === budget
                ? "border-ember-500/60 bg-ember-500/15 text-ember-400"
                : "border-ink-700 text-ink-400 hover:border-ink-600 hover:text-parchment-100"
            }`}
          >
            {formatEur(b, 0)}
          </button>
        ))}
        <span className="text-[11px] text-ink-400">par carte</span>
      </div>

      {resultat ? (
        <p className="mt-2 text-xs text-moss-400">
          ✓ {resultat.ajoutees} carte{resultat.ajoutees > 1 ? "s" : ""} ajoutée{resultat.ajoutees > 1 ? "s" : ""} à{" "}
          <Link href="/suivi" className="underline underline-offset-2">
            Ma liste
          </Link>
          {resultat.ajoutees > 1
            ? ", chacune avec sa cote comme budget. La chasse Vinted les cherchera"
            : ", avec sa cote comme budget. La chasse Vinted la cherchera"}{" "}
          ; Ma liste te montre les annonces qui passent sous ton budget.
        </p>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
          <p className="text-xs text-parchment-100/85">
            {aSuivre.length > 0 ? (
              <>
                {aSuivre.length} belle{aSuivre.length > 1 ? "s" : ""} version{aSuivre.length > 1 ? "s" : ""} te manque
                {aSuivre.length > 1 ? "nt" : ""} à moins de {formatEur(budget, 0)} —{" "}
                <span className="tabular font-mono">{formatEur(cout)}</span> en tout.
              </>
            ) : (
              <>Aucune belle version à suivre à moins de {formatEur(budget, 0)}.</>
            )}
            {dejaSuivies > 0 && (
              <span className="text-ink-400">
                {" "}
                {dejaSuivies} déjà dans Ma liste.
              </span>
            )}
            {auDela.length > 0 && (
              <span className="text-ink-400">
                {" "}
                {auDela.length} au-delà, dès {formatEur(Math.min(...auDela.map((c) => c.price_eur ?? 0)))}.
              </span>
            )}
          </p>
          {aSuivre.length > 0 && (
            <button
              type="button"
              onClick={chasser}
              disabled={occupe}
              className="rounded-md border border-amber-300/50 bg-amber-300/10 px-2.5 py-1 text-xs font-medium text-amber-200 transition-colors hover:bg-amber-300/20 disabled:opacity-60"
            >
              {occupe ? "…" : aSuivre.length > 1 ? "☆ Les suivre toutes" : "☆ La suivre"}
            </button>
          )}
        </div>
      )}
      {erreur && <p className="mt-2 text-xs text-rust-400">Rien n&apos;a été ajouté. [{erreur}]</p>}
    </div>
  );
}

/**
 * Ses cartes en vente en ce moment, les meilleures affaires d'abord, chacune
 * avec la carte qu'elle vend. Les photos sont celles du vendeur.
 */
function EnVente({ annonces, onOuvrir }: { annonces: AnnoncePersonnage[]; onOuvrir: (id: number) => void }) {
  return (
    <section className="mt-10">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <h2 className="font-display text-xl text-parchment-100">En vente en ce moment</h2>
        <p className="text-xs text-ink-400">Vinted et eBay, les meilleures affaires d&apos;abord · photos du vendeur</p>
      </div>
      {annonces.length === 0 ? (
        <p className="mt-2 text-xs text-ink-400">
          Aucune de ses cartes dans les annonces collectées en ce moment. Suis ses belles versions : Ma liste les
          cherchera sur Vinted.
        </p>
      ) : (
        <ul className="mt-3 grid list-none grid-cols-1 gap-2 p-0 md:grid-cols-2">
          {annonces.map((a) => (
            <Annonce
              key={a.id}
              annonce={a}
              entete={
                <button
                  type="button"
                  onClick={() => onOuvrir(a.carte.id)}
                  className="mb-1.5 flex w-full items-baseline justify-between gap-2 border-b border-ink-800 pb-1.5 text-left text-[11px] hover:text-ember-400"
                  title="Ouvrir la fiche de la carte"
                >
                  <span className="min-w-0 truncate text-parchment-100">
                    <span className="capitalize">{a.carte.version}</span> · {a.carte.card_code}
                    {a.carte.visuel ? <span className="text-ink-400"> · {a.carte.visuel}</span> : null}
                  </span>
                  <span className="shrink-0 text-ink-400">
                    {a.carte.exemplaires > 0 ? <span className="text-moss-400">✓ tu l&apos;as · </span> : null}
                    cote {a.carte.price_eur ? formatEur(a.carte.price_eur) : "—"}
                  </span>
                </button>
              }
            />
          ))}
        </ul>
      )}
    </section>
  );
}
