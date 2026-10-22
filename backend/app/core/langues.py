"""
Langue d'une fiche du catalogue.

CE QUE CETTE VALEUR DIT, EXACTEMENT
-----------------------------------
Elle ne dit pas « cette carte existe dans telle langue ». Elle dit : « le
nom affiché sur cette fiche est dans telle langue, et voici d'où il vient ».

    « fr »   la carte a été trouvée dans la liste officielle FRANÇAISE,
             et le nom affiché est celui imprimé sur la carte française ;
    « en »   la carte vient du relevé de la liste ANGLAISE et n'a pas (ou
             pas encore) été retrouvée côté français. Le nom affiché est
             donc l'anglais.
    None     inconnu : fiche créée par un import manuel qui ne l'a pas dit.

LA NUANCE QUI COMPTE
--------------------
Une fiche marquée « en » ne prouve pas que la carte n'est jamais parue en
français : elle prouve qu'on ne l'a pas trouvée dans les séries françaises
chargées jusqu'ici. La distinction a des conséquences pratiques — le jeu
français commence à OP09, donc les séries OP01 à OP08 n'y figurent pas du
tout — mais elle dépend aussi de ce qui a été chargé. L'interface dit donc
« pas trouvée dans la liste officielle française », pas « n'existe pas en
français ».
"""
FRANCAIS = "fr"
ANGLAIS = "en"

LIBELLES = {
    FRANCAIS: "Français",
    ANGLAIS: "Anglais",
}

# Formulation employée dans l'interface. Centralisée ici pour qu'elle reste
# la même partout : une carte anglaise décrite autrement d'un écran à
# l'autre laisserait croire à deux situations différentes.
EXPLICATIONS = {
    ANGLAIS: ("Nom anglais : cette carte n'a pas été trouvée dans la liste "
              "officielle française."),
    FRANCAIS: "Nom français, d'après la liste officielle du jeu.",
}


def libelle(code: str) -> str:
    return LIBELLES.get(code or "", "Langue inconnue")
