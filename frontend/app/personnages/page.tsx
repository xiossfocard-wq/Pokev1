"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import VisuelCarte from "@/components/VisuelCarte";
import { fetchPersonnages, type PersonnageResume } from "@/lib/api";
import { formatEur } from "@/lib/format";

/**
 * Les personnages appréciés — les icônes de la série et les personnages très
 * recherchés —, chacun avec sa page : toutes ses cartes, de la plus
 * accessible à la plus rare.
 */
export default function PersonnagesPage() {
  const [personnages, setPersonnages] = useState<PersonnageResume[] | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [recherche, setRecherche] = useState("");
  const [toutesLangues, setToutesLangues] = useState(false);

  useEffect(() => {
    setPersonnages(null);
    fetchPersonnages(toutesLangues)
      .then(setPersonnages)
      .catch((e) => setErreur(e instanceof Error ? e.message : String(e)));
  }, [toutesLangues]);

  const affiches = useMemo(() => {
    const q = recherche.trim().toLowerCase();
    return (personnages ?? []).filter((p) => !q || p.nom.toLowerCase().includes(q));
  }, [personnages, recherche]);
  const icones = affiches.filter((p) => p.calibre === "icone");
  const recherches = affiches.filter((p) => p.calibre === "recherche");

  return (
    <>
      <header className="sticky top-0 z-20 border-b border-ink-800 bg-ink-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2.5">
          <Link href="/" className="font-display text-lg leading-none text-parchment-100">
            Radar
          </Link>
          <span className="text-ink-400">/</span>
          <span className="text-sm text-parchment-100">Personnages</span>
          <div className="ml-auto flex gap-1.5">
            <Link
              href="/idees"
              className="rounded-md border border-amber-300/40 px-2.5 py-1.5 text-xs text-amber-200 transition-colors hover:border-amber-300"
            >
              ✦ Idées
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
        <h1 className="font-display text-2xl text-parchment-100">Personnages</h1>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-ink-400">
          Les icônes de la série et les personnages les plus recherchés. Chacun a sa page : toutes ses cartes, de la
          plus accessible à la plus rare, et par où commencer sa collection.
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
          <input
            type="search"
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
            placeholder="Chercher un personnage…"
            aria-label="Chercher un personnage"
            className="w-full max-w-xs rounded-md border border-ink-700 bg-ink-800/80 px-3 py-1.5 text-sm text-parchment-100 placeholder:text-ink-400 focus:border-ember-500 focus:outline-none"
          />
          <label className="flex items-center gap-2 text-xs text-ink-400">
            <input
              type="checkbox"
              checked={toutesLangues}
              onChange={(e) => setToutesLangues(e.target.checked)}
              className="accent-ember-500"
            />
            Inclure les séries sans version française
          </label>
        </div>

        {erreur && (
          <div className="mt-4 rounded-md border border-rust-500/40 bg-rust-500/10 px-3 py-2 text-xs text-rust-400">
            Impossible de charger les personnages. [{erreur}]
          </div>
        )}

        {!personnages && !erreur && (
          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="skeleton aspect-[63/110]" />
            ))}
          </div>
        )}

        {personnages && affiches.length === 0 && (
          <p className="mt-6 text-sm text-ink-400">Aucun personnage ne correspond.</p>
        )}

        {icones.length > 0 && <Groupe titre="Les icônes de la série" personnages={icones} />}
        {recherches.length > 0 && <Groupe titre="Très recherchés" personnages={recherches} />}
      </main>
    </>
  );
}

function Groupe({ titre, personnages }: { titre: string; personnages: PersonnageResume[] }) {
  return (
    <section className="mt-8">
      <h2 className="font-display text-xl text-parchment-100">{titre}</h2>
      <ul className="mt-3 grid list-none grid-cols-2 gap-3 p-0 sm:grid-cols-4 lg:grid-cols-6">
        {personnages.map((p) => (
          <li key={p.slug}>
            <Link
              href={`/personnages/${p.slug}`}
              className="group flex h-full flex-col overflow-hidden rounded-md border border-ink-700 bg-ink-900 transition-colors hover:border-ember-500/60"
            >
              <div className="relative aspect-[63/88] w-full bg-ink-950">
                <VisuelCarte
                  src={p.image_url}
                  alt={p.nom}
                  sizes="(max-width: 640px) 45vw, (max-width: 1024px) 25vw, 180px"
                  repli={() => (
                    <span className="flex h-full items-center justify-center p-2 text-center font-display text-lg text-ink-400">
                      {p.nom}
                    </span>
                  )}
                />
                {p.possedees > 0 && (
                  <span className="absolute left-1.5 top-1.5 rounded-sm border border-moss-500/60 bg-ink-950/85 px-1.5 py-0.5 text-[10px] text-moss-400">
                    ✓ {p.possedees}
                  </span>
                )}
              </div>
              <div className="flex flex-1 flex-col gap-0.5 p-2.5">
                <p className="font-display text-sm text-parchment-100 group-hover:text-ember-400">{p.nom}</p>
                <p className="text-[11px] text-ink-400">
                  {p.cartes} carte{p.cartes > 1 ? "s" : ""} · {p.belles} belle{p.belles > 1 ? "s" : ""} version
                  {p.belles > 1 ? "s" : ""}
                </p>
                {p.prix_min !== null && (
                  <p className="text-[11px] text-ink-400">
                    dès <span className="tabular font-mono text-parchment-100">{formatEur(p.prix_min)}</span>
                  </p>
                )}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
