/**
 * Vérifier une carte ailleurs : ce qu'on cherche sur Cardmarket et sur
 * CardNexus, pour une annonce comme pour une fiche du catalogue.
 *
 * Cardmarket nomme ses cartes One Piece « Shanks (OP01-120) (V.2) » : nom
 * anglais, CODE, puis version. Chercher le code trouve toutes les versions
 * et rééditions d'une carte (vérifié : « OP01-120 » renvoie ses 15 fiches),
 * là où « Shanks parallèle » ne trouve rien : Cardmarket ne connaît ni nos
 * mots de version, ni nos noms français.
 *
 * Sans code complet, le nom nettoyé suivi de l'extension (« Shanks OP14 »)
 * resserre la recherche sur les bonnes fiches.
 */

const CODE = /\b(?:OP|ST|EB|PRB)\d{2}-\d{3}\b/i;
// « OP14 », « OP-14 », « OP 14 » ; jamais le début d'un code complet.
const EXTENSION = /\b(OP|ST|EB|PRB)\s*-?\s*(\d{1,2})\b(?!-\d)/i;

// Ce qui n'est pas le nom de la carte dans un titre d'annonce ou une fiche :
// version, rareté, langue, état, gradation, mots de vendeur.
const BRUIT = new Set(
  (
    "parallele parallel alt art alternative alternate manga sp sec sr r uc c l leader tr treasure " +
    "fr francais francaise vf en eng anglais anglaise jp jap japonais japonaise japanese " +
    "carte cartes card cards one piece onepiece tcg cg nm mint near psa bgs cgc pca grade gradee " +
    "neuf neuve new holo foil rare super secret special promo version illustration v1 v2 v3 " +
    "lot de du des la le les et the a"
  ).split(" ")
);

function sansAccents(texte: string): string {
  return texte.normalize("NFD").replace(/[̀-ͯ]/g, "");
}

/** « OP-14 » → « OP14 ». */
export function extension(texte: string | null | undefined): string | null {
  const m = (texte ?? "").match(EXTENSION);
  return m ? `${m[1].toUpperCase()}${m[2].padStart(2, "0")}` : null;
}

/** Le nom de la carte, sans version, rareté, langue ni code. */
export function nomNettoye(texte: string): string {
  const sansParentheses = texte.replace(/\([^)]*\)/g, " ");
  return sansParentheses
    .replace(new RegExp(CODE.source, "gi"), " ")
    .replace(new RegExp(EXTENSION.source, "gi"), " ")
    .split(/[\s|/,;:!?+*#"«»()[\]{}]+/)
    .map((mot) => mot.replace(/^[-'.]+|[-'.]+$/g, ""))
    .filter((mot) => mot && !/^\d+$/.test(mot) && !BRUIT.has(sansAccents(mot).toLowerCase()))
    .join(" ")
    .trim();
}

/** La fiche à choisir sur Cardmarket : l'impression ordinaire est la V.1, la
 *  première illustration alternative la V.2, la seconde (le manga) la V.3. */
export function versionCardmarket(nameSlug: string | null | undefined): string {
  const rang = nameSlug?.match(/-(?:parallele|alternative|alt)(?:-(\d+))?$/);
  return rang ? `V.${(rang[1] ? Number(rang[1]) : 1) + 1}` : "V.1";
}

export interface CarteAVerifier {
  /** Code complet, s'il est connu : « OP14-027 ». */
  code?: string | null;
  /** Le nom de la fiche ou le titre de l'annonce. */
  nom: string | null | undefined;
  /** D'autres textes où trouver un code ou l'extension (« OP14 ») : le nom
   *  de l'extension, le titre de l'annonce. */
  indices?: string | null;
  /** « shanks-parallele-1 » : donne la version à choisir. Absent si la
   *  carte n'est pas identifiée. */
  nameSlug?: string | null;
  /** La fiche du catalogue, si on la connaît : CardNexus ouvre alors sa version exacte. */
  cardId?: number | null;
}

export interface Verification {
  cardmarketUrl: string;
  cardmarketTexte: string;
  /** La fiche à choisir parmi les résultats, si la carte est identifiée. */
  version: string | null;
  /** À coller dans la recherche de CardNexus : le nom et le code. */
  cardnexusTexte: string;
  /** Ce qui permet au serveur de trouver la page CardNexus de la carte. */
  cardnexus: { cardId: number | null; code: string | null; nom: string };
}

export const CARDNEXUS_URL = "https://cardnexus.com/fr/explore/onepiece";

export function verification(entree: CarteAVerifier): Verification {
  // Des annonces anciennes n'ont pas toujours de nom de carte : jamais de plantage.
  const carte = { ...entree, nom: entree.nom ?? "" };
  const code =
    (carte.code ?? carte.nom.match(CODE)?.[0] ?? carte.indices?.match(CODE)?.[0] ?? "").toUpperCase() || null;
  const nom = nomNettoye(carte.nom);
  const ext = extension(carte.nom) ?? extension(carte.indices);
  const version = carte.nameSlug ? versionCardmarket(carte.nameSlug) : null;

  let cardmarketTexte: string;
  if (code) cardmarketTexte = code;
  else if (nom && ext) cardmarketTexte = `${nom} ${ext}`;
  else cardmarketTexte = nom || carte.nom;

  return {
    cardmarketUrl: `https://www.cardmarket.com/fr/OnePiece/Products/Search?searchString=${encodeURIComponent(
      cardmarketTexte
    )}`,
    cardmarketTexte,
    version,
    cardnexusTexte: [nom, code ?? ext].filter(Boolean).join(" ") || carte.nom,
    cardnexus: { cardId: carte.cardId ?? null, code, nom: nom || carte.nom },
  };
}
