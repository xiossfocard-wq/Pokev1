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
