/**
 * Les nombres tels qu'un acheteur français les lit : « 62,20 € », pas
 * « 62.20 € ». Le catalogue affichait le second, le radar le premier : deux
 * conventions sur un même écran, et une virgule anglaise sur un prix.
 */
export function formatEur(value: number | null | undefined, decimales = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("fr-FR", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
}

/** Un nombre sans unité, au format français : « 1,20 ». */
export function formatNombre(value: number, decimales = 2): string {
  return value.toLocaleString("fr-FR", {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
}

/** Une fourchette de prix : « 1,20 – 3,40 € ». */
export function formatFourchette(bas: number, haut: number): string {
  return `${formatNombre(bas)} – ${formatEur(haut)}`;
}

/**
 * « il y a 12 min ». Le serveur rend ses dates en UTC sans fuseau : on le
 * précise, sinon le navigateur les lirait en heure locale, décalées d'une à
 * deux heures.
 */
export function ilYA(iso: string | null | undefined): string {
  if (!iso) return "jamais";
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  const minutes = Math.floor((Date.now() - date.getTime()) / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const heures = Math.floor(minutes / 60);
  if (heures < 24) return `il y a ${heures} h`;
  return `il y a ${Math.floor(heures / 24)} j`;
}
