"use client";

import Image from "next/image";
import { useState, type ReactNode } from "react";

// L'illustration d'une carte, avec un repli quand elle ne charge pas.
//
// Une adresse en base ne garantit pas une image à l'écran : l'hôte peut être
// injoignable, l'illustration retirée, ou l'adresse déduite du code sans que
// le site la publie finalement. Sans repli, le navigateur affichait un cadre
// cassé — un défaut visible sur la carte même qu'on regarde pour décider
// d'acheter.
//
// « no-referrer » : un site peut refuser une image demandée depuis une page
// qui n'est pas la sienne. Ne pas transmettre la page d'origine fait charger
// l'image comme si on l'ouvrait directement, et évite au passage d'envoyer
// l'adresse locale de l'application à un site tiers.
export default function VisuelCarte({
  src,
  alt,
  sizes,
  repli,
}: {
  src: string | null | undefined;
  alt: string;
  sizes: string;
  // Ce qui s'affiche à la place, avec la raison : pas encore d'adresse, ou
  // une adresse qui n'a pas donné d'image. Les deux n'appellent pas la même
  // lecture.
  repli: (raison: "absent" | "echec") => ReactNode;
}) {
  // On retient l'adresse qui a échoué plutôt qu'un simple booléen : le
  // composant est réutilisé d'une carte à l'autre, et un échec ne doit pas
  // masquer l'image de la carte suivante.
  const [enEchec, setEnEchec] = useState<string | null>(null);

  if (!src) return <>{repli("absent")}</>;
  if (enEchec === src) return <>{repli("echec")}</>;

  return (
    <Image
      src={src}
      alt={alt}
      fill
      sizes={sizes}
      className="object-contain"
      unoptimized
      referrerPolicy="no-referrer"
      onError={() => setEnEchec(src)}
    />
  );
}
