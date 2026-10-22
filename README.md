# One Piece Deal Hunter

Deux outils complémentaires sur la même base de données, qui répondent à
deux questions différentes.

**1. Explorer le catalogue** (`/explorer`) — *quelle carte vaut la peine ?*
Chercher parmi toutes les cartes connues par **thème** (l'équipage du
Chapeau de Paille, la Marine, les Grands Corsaires…), par **type de carte**
(Secret Rare, Manga Rare, alternative, Leader…), par **budget** et par
**tendance**,
avec le **visuel de chaque carte**. Les cartes en vogue sont classées sur la
variation 7 jours, en pourcentage.

**2. Chasser les bonnes affaires** (`/`) — *où l'acheter au bon prix ?*
Surveillance des annonces Vinted et eBay (cartes One Piece FR), comparées à
des prix de référence (Cardmarket + ZebraDex), avec un score de "bonne
affaire" combinant marge estimée, qualité indicative (photos + texte) et
fiabilité vendeur. Notifications Telegram/email au-dessus d'un seuil
configurable, dashboard trié par score/marge/date.

On repère une carte intéressante dans l'explorateur, on la traque ensuite
dans les annonces.

## ⚠️ À lire avant de lancer : limites légales du scraping

Ce projet accède à des données Vinted, Cardmarket et ZebraDex sans API
officielle (Vinted et ZebraDex n'en proposent pas ; Cardmarket en a une
mais elle est contractuellement réservée à la gestion de son propre stock —
voir `backend/app/collectors/cardmarket_prices.py`). Pour ces trois
sources :

- **Aucune connexion à un compte** : seules des pages publiques sont lues.
- **Fréquence volontairement basse** (configurable), avec pause automatique
  en cas de blocage.
- **robots.txt vérifié automatiquement avant chaque requête** (voir
  `app/core/robots_compliance.py`) : si un site l'interdit, la requête est
  annulée, pas de contournement.
- **Aucun contournement d'anti-bot** : pas de rotation de proxy, pas de
  résolution de CAPTCHA. Si un site bloque, le scraper recule et te
  notifie plutôt que d'insister.

Malgré ces précautions, les CGU de Vinted interdisent probablement
l'extraction automatisée de données hors de l'interface prévue par le site
(clause courante chez la plupart des plateformes de ce type) : c'est un
usage à tes risques, en usage personnel et à faible volume, pas une
autorisation formelle de leur part. Le risque concret le plus probable est
un blocage temporaire de ton IP, pas une poursuite — mais sois-en conscient.
Cardmarket a rendu son "Price Guide" librement consultable précisément pour
ce genre d'usage ; ZebraDex n'a pas de politique connue là-dessus.

## Architecture

```
backend/   FastAPI + SQLAlchemy + APScheduler (Python)
frontend/  Next.js 14 (App Router) + Tailwind
```

- **Collecte** : `app/collectors/` — eBay Browse API (officielle, OAuth2),
  scraper Vinted (respectueux), Cardmarket (page produit ou price guide en
  masse), ZebraDex (pages série).
- **Matching carte** : `app/matching/card_matcher.py` — devine le nom de
  carte à partir du titre de l'annonce (best-effort, voir limites dans le
  fichier). Rattrapage possible via OCR photo si le titre ne suffit pas.
- **Scoring** : `app/scoring/` — marge, qualité texte, fiabilité vendeur,
  score final combiné (poids configurables).
- **Vision/OCR** : `app/vision/quality_vision.py` — un seul appel à l'API
  Anthropic (Claude) par annonce fait à la fois l'estimation d'état
  (centrage/coins/rayures, **indicative, pas un grading pro**) et la
  lecture du nom/numéro imprimés sur la carte.
- **Notifications** : `app/notifications/` — Telegram et/ou email.
- **Orchestration** : `app/pipeline.py` (logique) + `app/scheduler.py`
  (déclenchement périodique) + endpoint `POST /api/admin/run-check-now`
  pour déclencher un cycle manuellement (utile en debug, et pour
  l'hébergement 100% gratuit — voir plus bas).

## Explorer le catalogue : ce qui est solide et ce qui ne l'est pas

### Les thèmes

`backend/app/services/card_themes.py` classe chaque carte dans deux familles
de thèmes, qui se cumulent :

- **par sujet** : équipage du Chapeau de Paille, Pires Générations, équipages
  du Cœur, de Kid, du Roux, aux Cent Bêtes, de Big Mom, de Barbe Blanche, de
  Barbe Noire, Marine, Grands Corsaires, Armée Révolutionnaire, famille
  Donquixote ;
- **par type de carte** : Secret Rare, Super Rare, Manga Rare, alternative /
  parallèle, Leader, promotionnelle.

« Monkey D. Luffy (Secret Rare) » appartient donc à la fois à
`chapeau-de-paille`, `pires-generations` et `secret-rare` : ce sont trois
façons distinctes de chercher la même carte.

C'est une **heuristique sur le nom**, pas une base de données One Piece
exhaustive. Les graphies françaises anciennes sont prévues en alias
(Zorro, Pipo, Baggy), tout comme les noms anglais. Un thème raté n'enlève
rien à la carte, qui reste trouvable par la recherche libre. Pour ajouter un
thème : compléter `card_themes.py`, puis `POST /api/admin/recompute-card-fields`
pour rattraper les cartes déjà en base.

**Deux axes majeurs du jeu manquent volontairement** : la **couleur** (rouge,
vert, bleu, violet, noir, jaune) et le **type de carte** (Leader, Personnage,
Événement, Stage). Ni l'un ni l'autre ne se lit dans le nom d'une carte : il
faut que la source les publie. Les deviner donnerait un filtre faux, ce qui
est pire qu'un filtre absent. Seul le Leader est reconnu, et uniquement quand
la rareté le dit explicitement.

### La recherche

Elle est **insensible à la casse et aux accents** : « Portgás », « portgas »
et « PORTGAS » ramènent la même carte.

Ce n'était pas gratuit. Chercher directement sur le nom affiché échouait
pour deux raisons cumulées : le `lower()` de SQLite ne traite que l'ASCII,
donc « Portgás » y restait inchangé alors que Python en faisait « portgás » ;
et personne ne tape les accents, or la graphie sans accent ne correspondait
ni au `name_slug` (avec des tirets) ni au nom affiché, y compris sous
Postgres. Une colonne `search_key` normalisée est donc calculée à
l'écriture, et la requête est normalisée de la même façon.

**Après le déploiement, lancer une fois `POST /api/admin/recompute-card-fields`** :
les cartes synchronisées avant l'existence de cette colonne ne la portent
pas. Un repli sur le slug et sur le code de carte évite que la recherche
devienne vide entre-temps, mais il est moins précis.

### Les tendances : deux choses très différentes

**La variation 7 jours est une vraie donnée**, publiée par ZebraDex et déjà
collectée pour chaque carte. C'est elle qui alimente « en vogue cette
semaine », disponible immédiatement.

Le classement se fait **en pourcentage, pas en euros**. Un classement en
euros ne dirait rien d'autre que « les cartes chères bougent de plus gros
montants » : +12 € sur une carte à 400 € est du bruit, +12 € sur une carte à
8 € est un triplement.

**La tendance de fond, elle, part de zéro.** La source ne publie qu'un prix
instantané : il n'existe aucun historique à récupérer, et le passé ne se
reconstitue pas après coup. Le projet constitue donc le sien, à raison d'un
relevé par carte et par jour (`card_price_snapshots`, tâche planifiée à
03:00, ou `POST /api/admin/snapshot-card-prices` à la main). **Chaque jour
où ce relevé ne tourne pas est un trou définitif dans la courbe.**

### Les « prédictions », et pourquoi elles sont prudentes

Tant que l'historique compte moins de 5 relevés étalés sur moins de 7 jours,
l'API rend `projection.prix_projete_eur = null` et dit pourquoi. C'est
volontaire : un prix projeté calculé sur deux relevés est un chiffre
inventé, et un chiffre inventé affiché à côté de vrais prix est lu comme un
vrai prix.

Au-delà de ce seuil, ce qui est rendu est une **extrapolation linéaire**,
pas une prévision : elle prolonge la pente récente en supposant que rien ne
change. Sur des cartes à collectionner, une réimpression, un résultat de
tournoi ou une vidéo virale peuvent tout retourner en une semaine. Le `r²`
dit à quel point les relevés passés s'alignent réellement sur cette droite,
et l'avertissement est porté jusqu'à l'interface. À lire comme une tendance
prolongée, jamais comme une valeur future.

### ⚠️ Quatre réglages à renseigner avant que la collecte serve à quelque chose

Le projet ne vise **que** One Piece. Ces valeurs dépendent de sources que
l'environnement de développement ne peut pas joindre, et aucune n'a donc pu
être vérifiée.

| Réglage | Défaut | À faire |
|---|---|---|
| `VINTED_BRAND_ID` | vide | Facultatif mais recommandé. Ouvre une annonce One Piece sur vinted.fr, suis le lien de la marque, relève le nombre dans `/brand/<id>-<nom>`. |
| `ZEBRADEX_TCG_SLUG` | `one-piece` | ⚠️ **Sans objet : ZebraDex ne couvre pas One Piece.** Vérifié le 15/10/2026 dans un navigateur — le sitemap FR ne contient que `/fr/tcg/pokemon` (336 séries) et `/fr/tcg/one-piece` rend 404. Voir ci-dessous. |
| `CARDMARKET_GAME_PATH` | `OnePiece` | Vérifie le segment dans l'URL d'une carte One Piece sur cardmarket.com. |
| `CARD_IMAGE_BASE_URL` | liste officielle du jeu | Confirme avec `GET /api/admin/debug-card-images?code=OP01-001` : la réponse donne le code HTTP de chaque adresse essayée. |

Le filtre de marque Vinted mérite une explication. Il était **figé sur
l'identifiant d'une autre marque** : chaque recherche restait filtrée
dessus et ne pouvait donc remonter aucune carte One Piece. C'était le défaut
le plus grave, et il était silencieux. Par défaut, plus aucun
filtre de marque n'est appliqué : la recherche se fait sur le seul texte,
moins précise mais juste. Mieux vaut trop d'annonces que les annonces d'un
autre jeu.

### ⚠️ Le catalogue n'a pas encore de source

**ZebraDex ne couvre pas One Piece.** Constaté le 15/10/2026 depuis un
navigateur réel, après déploiement : le sitemap FR ne liste que
`/fr/tcg/pokemon`, et `/fr/tcg/one-piece` renvoie 404. Ce n'est pas un slug
à corriger — la section n'existe pas.

C'est le défaut le plus coûteux du projet, et sa cause est instructive : la
couverture One Piece de ZebraDex avait été **supposée**, jamais constatée,
parce que l'environnement de développement ne peut pas joindre le site. Tout
le reste en dépendait. Sans catalogue : pas de codes de cartes, donc pas de
prix de référence, donc pas de score d'affaire, et pas de visuels non plus
puisqu'ils se déduisent du code.

**Ce qu'il faut à la place.** Le catalogue a besoin, par carte : un code
(`OP01-120`), un nom, une série, une rareté et un prix. Aucune source connue
ne donne les cinq — la liste officielle du jeu donne tout sauf le prix, un
guide de prix donne le prix et le nom mais rarement le code. L'architecture
visée est donc à deux sources : la structure d'un côté, les prix de l'autre.

**Les deux sources retenues** (désignées le 15/10/2026) :

| Source | Ce qu'elle apporte |
|---|---|
| `fr.onepiece-cardgame.com/cardlist/` | code, nom **français**, rareté, visuel — pas de prix |
| `www.opecards.fr` | prix en euros, pour des cartes françaises |

Le **français** n'est pas un détail de confort : l'édition anglaise porte
d'autres noms imprimés, et un catalogue rempli avec elle ne se rapprocherait
d'aucune annonce française. C'est aussi pourquoi `CARD_IMAGE_BASE_URL` vise
`fr.`, pas `en.`.

**Comment on choisit, cette fois.** `GET /api/admin/debug-catalog-sources`
interroge ces sources depuis le backend déployé — qui a un accès réseau
normal, contrairement à l'environnement de développement — et rapporte ce
que chacune répond : code HTTP, type de contenu, extrait brut, **les liens
internes rencontrés** (c'est eux qui révèlent comment le site adresse ses
séries et ses fiches), le nombre de prix en euros visibles, et les mots
français repérés. **Elle ne parse rien et ne décide rien.** Le parseur sera
écrit contre la forme réellement observée.

La sonde distingue « robots.txt interdit » de « robots.txt illisible ». Les
deux l'empêchent de sonder, mais appellent des suites opposées : le premier
ferme la source, le second dit seulement que l'hôte n'a pas répondu. Les
confondre ferait dire au diagnostic le contraire de la réalité — précisément
l'erreur à ne pas refaire.

### Les visuels — ⚠️ format d'adresse non vérifié

ZebraDex ne publie pas d'image exploitable. Les visuels viennent donc de la
**liste officielle du jeu** (`backend/app/collectors/card_images.py`).

**Par le code de la carte, pas par son nom.** C'est le point important.
L'illustration de `OP01-120` vit à une adresse qui se déduit directement de
ce code : `<base>/OP01-120.png`. Pas de recherche, pas d'API, pas
d'ambiguïté. Chercher **par nom**, comme le ferait une API d'illustrations
généraliste, serait beaucoup moins sûr : une quarantaine de cartes
s'appellent « Luffy », et la réponse pourrait être le visuel d'une autre
carte, affiché sous un prix. Montrer la mauvaise image est pire que n'en
montrer aucune — c'est justement l'image qu'on regarde pour décider
d'acheter.

**Chaque adresse est vérifiée avant d'être enregistrée.** Construire une URL
ne prouve pas qu'elle existe. Le collecteur fait une requête de contrôle
(`HEAD`, avec repli sur `GET` si l'hôte refuse `HEAD`) et n'enregistre que si
la réponse est **bien une image** — statut 200 *et* type de contenu
`image/*`. Un 200 qui rend une page HTML d'erreur, piège classique, est
rejeté. Conséquence assumée : quand la vérification ne peut pas aboutir,
aucune image n'est enregistrée et l'interface affiche le cadre vide prévu
pour ça, plutôt qu'un cadre cassé.

⚠️ **Le format d'adresse n'a pas pu être vérifié.** La politique réseau de
l'environnement de développement refuse `en.onepiece-cardgame.com`, comme
tous les hôtes de données de cartes. Le format est donc écrit d'après la
forme publique connue — et reste **réglable sans toucher au code** :

```bash
CARD_IMAGE_BASE_URL=https://…/images/cardlist/card   # backend
NEXT_PUBLIC_CARD_IMAGE_HOST=autre-hote.example       # frontend, si l'hôte change
```

Le réglage frontend n'est pas un oubli : `next/image` refuse tout hôte absent
de `next.config.js`. Changer la base côté backend sans renseigner l'hôte côté
frontend casserait l'affichage, et le lien entre les deux serait très
difficile à retrouver.

Si aucun visuel ne remonte : `GET /api/admin/debug-card-images?code=OP01-001`
rend le **détail de chaque tentative** — code HTTP et type de contenu. La
réponse dit s'il s'agit d'un 404 (format à corriger), d'un 403 (hôte qui
refuse les requêtes automatisées) ou d'une panne réseau. Copie-la-moi et
j'ajuste. Même démarche que `debug-vinted` et `debug-zebradex`.

Trois comportements à connaître :

- les **illustrations alternatives** (*parallel*, *manga*, *alt art*) sont
  servies sous le même code suffixé `_p1`, `_p2`. Quand le nom de la carte
  annonce une alternative, ces variantes sont essayées **en premier** : c'est
  bien cette illustration-là qui est en vente au prix affiché ;
- une carte **sans code** ne génère aucune requête et sort de la file
  d'enrichissement. Aucune adresse n'est déductible pour elle, et la garder
  reviendrait à lui réserver des places, dans un lot de taille fixe, pour un
  échec garanti ;
- l'enrichissement est **progressif** (quelques dizaines de cartes par
  passage, toutes les 30 minutes). Sur un gros catalogue, les visuels se
  remplissent sur plusieurs heures, les cartes les plus chères d'abord.

### Remplir le catalogue depuis un fichier

Le catalogue n'avait **qu'une seule** façon d'être rempli : la
synchronisation ZebraDex. Quand cette source s'est révélée ne pas couvrir
One Piece, il n'est rien resté. Le défaut n'était pas le choix de la
source, c'était qu'il n'y avait qu'un chemin.

`POST /api/admin/import-catalog` en ouvre un second, qui ne dépend ni du
réseau ni de la forme d'une page :

```bash
curl -X POST http://localhost:8000/api/admin/import-catalog \
     --data-binary @cartes.csv
```

Le corps de la requête **est** le fichier — CSV (`;` ou `,`) ou JSON,
reconnu tout seul.

| Colonne | | Exemple |
|---|---|---|
| `card_code` | **obligatoire** | `OP01-120`, `OP01 120`, `OP01-4` |
| `display_name` | **obligatoire** | le nom **français** imprimé |
| `price_eur` | **obligatoire** | `12,50 €`, `1 234,56`, `12.50` |
| `series_name` | facultatif | `Romance Dawn` |
| `rarity` | facultatif | `Secret Rare` |

Les intitulés français courants sont acceptés : `code`, `nom`, `prix`,
`serie`, `rarete`. La virgule décimale est le cas normal, pas l'exception.

Rien d'autre n'est demandé. **Les thèmes, la clé de recherche et le visuel
sont dérivés** — le visuel se déduit du code et se remplit tout seul au
passage suivant de l'enrichissement.

**Chaque ligne refusée est rendue avec son numéro et sa raison**, et
`lues = importées + rejetées` est vérifié par un test. Un import qui
avalerait silencieusement la moitié d'un fichier reproduirait exactement le
silence qui a laissé croire que le catalogue se remplissait alors qu'il
restait vide.

Un défaut trouvé en important de vraies cartes, qui valait d'être corrigé :
le slug écrit par l'import doit avoir **exactement** la forme que le parseur
de titre produit. « Monkey D. Luffy » donnait `monkey-d.-luffy` avec le
point, là où le parseur cherche `monkey-d-luffy` : les deux ne se
rencontraient jamais, et le prix retombait sur le nom usuel — moins sûr —
sans que rien ne le signale. Un test verrouille leur égalité.

### Le rapprochement annonce → carte

Une annonce ne vaut rien sans prix de référence : c'est lui qui dit si
c'est une affaire. Le rapprochement se fait en cascade, du plus sûr au
moins sûr, et **s'arrête au premier niveau qui répond** :

1. **le code carte** (`OP01-120`) — le seul cas où on est vraiment sûr ;
2. **le nom complet** (`Monkey D. Luffy`) ;
3. **le nom usuel** (`Luffy`) — voir ci-dessous ;
4. **la faute de frappe** (`zorro` → `zoro`), volontairement sévère.

Le niveau 3 est propre à One Piece. Le jeu indexe ses cartes sous le nom
complet du personnage, alors que les vendeurs écrivent le nom usuel : «
Luffy », « Ace », « Katakuri ». Sans ce rattrapage, **la majorité des
annonces du jeu ne trouvaient aucun prix** dès que le titre ne portait pas
le code.

La règle est étroite à dessein : le candidat doit être la **fin** du nom
indexé, sur des mots entiers. « luffy » retrouve « monkey-d-luffy », «
ace » retrouve « portgas-d-ace » mais **pas** « menace ». L'inverse — un
candidat qui serait le début — ne correspond à rien d'observé : personne
n'écrit « Monkey » pour désigner Luffy.

Deux garde-fous :

- **plusieurs cartes finissent par le même nom** → la médiane est retenue,
  mais la confiance tombe à *basse*, l'écart de prix est exposé et
  l'annonce est marquée incertaine. Trois cartes « Luffy » de 2,40 € à
  412 € : le prix médian ne veut pas dire grand-chose, et l'utilisateur
  doit le savoir ;
- **plus de douze cartes** finissent par ce nom → **aucun prix**. Une
  médiane tirée de trente cartes allant de 2 à 400 € est un chiffre qui
  ment ; mieux vaut l'absence.

Le code reste prioritaire sur tout : « Luffy OP01-120 » donne le prix de
cette carte-là, en confiance haute.

### Les bonnes affaires dans la fiche carte

Les deux moitiés de l'app sont reliées. Le catalogue sert à repérer une
carte ; la fiche de cette carte montre **ce qui est en vente maintenant**,
sans repasser par le tableau de bord.

`Listing.matched_card_id` est la colonne qui rend ce lien possible. Le
rapprochement annonce → carte existait déjà, mais **seulement à l'intérieur
d'un blob JSON** (`price_detail`), donc impossible à joindre en SQL : on ne
pouvait pas demander « les annonces de cette carte ». La colonne est
maintenant renseignée à l'enregistrement et indexée.

**Depuis la grille, sans ouvrir les fiches.** Chaque vignette porte un badge
« 3 en vente · 92 » quand des annonces existent, et le filtre *Seulement les
cartes en vente* ne garde que celles-là. C'est ce qui rend la boucle
utilisable : repérer une carte par thème ou par tendance, puis voir
immédiatement laquelle mérite qu'on l'ouvre — au lieu de les ouvrir une par
une. Le compte est agrégé en **une seule requête** pour toute la page.

Les trois vues qui affichent ce compte — la grille, le rail « en vogue » et
la fiche — passent par **le même prédicat d'exclusion**
(`_annonces_visibles`). Si elles divergeaient, la grille promettrait une
affaire que la fiche ne montrerait pas, ce qui est pire que pas de compteur
du tout. Un test verrouille leur égalité.

`GET /api/cards/{id}/listings` applique **les mêmes exclusions que le tableau
de bord** — annonces ignorées, indisponibles, retirées, masquées à la main,
sous le prix plancher — et trie par score d'affaire décroissant. Deux vues
qui se contrediraient sur ce qui est « en vente » seraient pires qu'une
seule.

Les photos affichées sont celles **du vendeur**, pas l'illustration
officielle. C'est volontaire : pour décider d'acheter, ce qui compte est
l'exemplaire réel, son centrage, ses bords, son état. L'illustration
officielle est en haut de la fiche et sert à identifier la carte, pas à juger
la marchandise. Chaque annonce affiche le prix, le port, le total, le score
d'affaire, la marge nette estimée, l'état, la fiabilité du vendeur, et
signale un **rapprochement incertain** quand il l'est — ce dernier point
compte : un score flatteur sur une carte mal identifiée est un piège.

### Routes

| Route | Usage |
|---|---|
| `GET /api/cards` | Recherche filtrée : `q`, `theme`, `rarity`, `series`, `price_min`, `price_max`, `trend`, `with_image`, `with_listings`, `sort_by`, `order`, `limit`, `offset` |
| `GET /api/cards/themes` | Thèmes avec nombre de cartes et fourchette de prix |
| `GET /api/cards/filters` | Valeurs réellement présentes en base, pour les listes déroulantes |
| `GET /api/cards/trending` | Plus fortes variations 7 jours, en pourcentage |
| `GET /api/cards/{id}` | Fiche : thèmes, historique, tendance de fond, projection |
| `GET /api/cards/{id}/listings` | Annonces en vente pour cette carte, photos du vendeur incluses |
| `POST /api/admin/snapshot-card-prices` | Relevé de prix du jour (rattrapage manuel) |
| `POST /api/admin/enrich-card-images` | Complète les visuels manquants |
| `POST /api/admin/recompute-card-fields` | Rattrape les thèmes et la clé de recherche (à lancer une fois après le déploiement) |
| `POST /api/admin/import-catalog` | Remplit le catalogue depuis un CSV ou un JSON |
| `GET /api/admin/debug-catalog-sources` | Quelles sources peuvent alimenter le catalogue, et sous quelle forme |
| `GET /api/admin/debug-card-images` | Détail de chaque adresse d'image essayée pour un code |

**Tests** : `backend/tests/` — 466 tests. Lancer avec :

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt --break-system-packages
python3 -m unittest discover -s tests -v
```

Ils couvrent deux niveaux :

- **la logique pure** (marge, score, matching, parsing
  eBay/Vinted/Cardmarket/ZebraDex, robots.txt, filtre de langue,
  corrections manuelles, vision/OCR avec l'appel API mocké) ;
- **le catalogue** (classement thématique, tendances, relevés de prix,
  refus de projeter sur un historique trop court, parsing des visuels
  testé hors réseau) ;
- **les deux API** (`tests/test_api_routes.py`,
  `tests/test_card_catalog_api.py`) : le serveur démarre
  pour de vrai, les routes sont montées aux bons chemins, les annonces se
  sérialisent en JSON, et les codes d'erreur sont ceux annoncés (404 sur
  annonce inconnue, 400 sur action de correction invalide). Ce module a
  besoin de `httpx` (dans `requirements-dev.txt`) ; sans lui il est sauté
  proprement et le reste de la suite tourne quand même.

**Vérifié à la main le 02/09/2026**, en plus de la suite : le backend
démarre (`init_db` + rattrapage de colonnes + scheduler), les 18 routes
répondent, et le frontend compile (`next build`, vérification de types
comprise, 3 pages générées).

**En intégration continue** (`.github/workflows/`) : `backend-tests.yml`
lance la suite à chaque push touchant `backend/`, et `frontend-build.yml`
compile le frontend (vérification TypeScript comprise) à chaque push
touchant `frontend/` — auparavant une erreur de types n'apparaissait qu'au
déploiement Vercel.

Le workflow backend contient une étape qui peut surprendre : elle échoue si
les tests d'API sont **sautés**. Un test sauté ne fait pas échouer unittest,
si bien que la CI affichait `OK` alors qu'elle n'installait pas `httpx` et
n'exécutait donc aucun de ces tests. Un vert qui ne vérifie rien est plus
dangereux qu'un rouge : cette étape rend le cas impossible à ignorer.

Ce qui reste **non testé en conditions réelles** : tout ce qui touche au
réseau sortant — collecte eBay et Vinted, Cardmarket, ZebraDex,
notifications — et le déclenchement périodique du scheduler. Ces
chemins-là ne peuvent être validés que sur ton installation, avec de
vraies clés : je reste disponible pour déboguer à partir des erreurs que
tu me copieras-colleras.

## Lancer en local (le chemin recommandé)

Pour un usage personnel, le local est le meilleur choix, et pas seulement
par simplicité :

- **Vinted répond mieux depuis une connexion résidentielle.** Son anti-bot
  est nettement plus hostile aux IP de datacenter. C'est le gain le plus
  concret ;
- **pas de mise en veille** : l'hébergement gratuit s'endort après 15 min
  et le réveil coûte 30 à 60 secondes ;
- **pas de cron externe** : le planificateur tourne dans l'app. Le workflow
  GitHub `trigger-check` n'existe que pour réveiller un hébergement
  endormi, et avec lui disparaît la question du quota Actions ;
- **pas de base à provisionner** : SQLite, créée au premier démarrage.

Le compromis : **ça ne collecte que quand le PC est allumé**, et il n'y a
pas d'accès depuis le téléphone. Les deux ne s'excluent pas — même code,
deux configurations.

### Ce qu'il faut avoir

| | | |
|---|---|---|
| **Python 3.11+** | indispensable | tout le moteur est en Python |
| **Node.js 20+** | indispensable | c'est lui qui fait l'interface web |
| **Git** | optionnel | sert seulement à récupérer le code |

Sans Git : sur la page du dépôt, bouton **Code** → **Download ZIP**, puis
décompresser et ouvrir un terminal dans le dossier.

### En une commande

```bash
bash scripts/demarrer.sh
```

À lancer sur **votre** machine : c'est elle qui joint les sites de
référence. Le script dit d'emblée ce qui manque, et le dit en une fois.

Il installe ce qui manque, lance l'API, **remplit le catalogue**, récupère
les visuels puis démarre l'interface. `Ctrl+C` arrête tout.

Sous Windows : depuis Git Bash ou WSL. Sinon, suivre les étapes manuelles
ci-dessous, qui font exactement la même chose.

### Aucune configuration n'est nécessaire

Vérifié le 20/10/2026 sur un clone neuf, sans `.env` et sans aucune
variable d'environnement : le backend démarre en une seconde, crée
`dev.db` et ses sept tables, et le frontend lui parle sans réglage — les
deux pointent déjà sur `localhost:8000`.

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

API sur http://localhost:8000 — vérifier avec `curl http://localhost:8000/api/health`.

Copier `.env.example` en `.env` seulement pour ajouter des clés
optionnelles (eBay, Telegram, Anthropic). Rien n'est obligatoire.

### Remplir le catalogue — l'étape qu'on ne devine pas

Le catalogue ne se remplit **pas** tout seul au premier démarrage. Sans
cette étape l'application se lance correctement, n'affiche aucune carte,
et rien n'indique que c'est normal.

```bash
curl -X POST http://localhost:8000/api/admin/load-opcg-catalog
```

Environ 3 870 cartes, lues dans un instantané versionné du dépôt : ni
réseau ni fichier à fournir. Ajouter `?rafraichir=true` pour aller
chercher la dernière version publiée à la place.

### Puis les noms français

L'instantané vient d'un relevé de la liste **anglaise**. Pour les
personnages cela passe — « Roronoa Zoro » s'écrit pareil des deux côtés —
mais c'est faux là où ça compte :

| anglais | français |
|---|---|
| Buggy | **Baggy** |
| Hive | **Ruche** |
| Three Sweet Commanders | **Trois généraux sucrés** |

Les cartes Événement sont intégralement traduites. Sans cette étape, un
vendeur français qui écrit « Baggy » ne rencontre jamais la fiche.

Les cartes que la liste française ne contient pas **restent au catalogue**,
marquées « nom anglais » : le jeu français n'a commencé qu'à la série OP09,
donc les séries antérieures n'y figurent pas du tout. Elles sont signalées,
pas masquées — un filtre « Langue du nom » permet de les isoler ou de les
écarter.

```bash
curl -X POST http://localhost:8000/api/admin/load-fr-names
```

L'opération **renomme** les fiches existantes au lieu d'en créer de
nouvelles — le catalogue est indexé sur (code, nom), et un import classique
aurait laissé « Buggy » et « Baggy » côte à côte pour la même carte. Les
prix de référence ne sont pas touchés, et les visuels sont rangés au
passage : la page publie leur adresse exacte.

### Puis les prix — c'est ce qui allume les marges

```bash
curl -X POST http://localhost:8000/api/admin/load-fr-prices
```

Prix de référence en euros, depuis **OPECards.fr** (qui les relève chez
Cardmarket), avec leur variation récente. Sans eux, une annonce peut être
identifiée mais pas jugée : pas de marge, pas de score, pas de bonne
affaire.

**Le rapprochement se fait sur (code, rang de variante), et pas sur le code
seul.** La raison tient en trois lignes, relevées le 22/10/2026 :

| `OP15-118-SEC` | prix |
|---|---|
| Ener | 10,50 € |
| Ener (Version 2) | 22,00 € |
| Ener (Version 3) | **695,00 €** |

Un code désigne jusqu'à quatre cartes dont les prix vont de 10 € à 695 €.
Les confondre ne fait pas une petite imprécision : ça fabrique une marge
fausse, et une marge fausse ne se voit pas.

Une carte absente du catalogue n'est pas créée ici — cette source dit ce
que valent les cartes, pas lesquelles existent. Lancer `load-fr-names`
avant.

### Et les visuels

Pour les cartes que l'étape précédente n'a pas couvertes. Ils se déduisent
du code, arrivent par lots de 200, donc il faut relancer l'appel une
vingtaine de fois — ou laisser le script le faire :

```bash
python3 scripts/etapes_demarrage.py visuels
```

**Ce que cette source ne donne pas : les prix.** Elle dit quelles cartes
existent, pas ce qu'elles valent. Les cartes entrent donc sans prix de
référence, et l'interface l'écrit noir sur blanc plutôt que d'afficher un
`0,00 €` qui se lirait comme « cette carte ne vaut rien ». Les marges et
les scores d'affaire restent vides tant qu'une source de prix n'est pas
branchée — par exemple un fichier avec une colonne prix :

```bash
curl -X POST http://localhost:8000/api/admin/import-catalog \
     --data-binary @mes-prix.csv
```

Il met à jour les mêmes fiches sans les dupliquer, et un import sans
colonne prix n'efface jamais les prix déjà connus.

### Frontend

Dans un second terminal :

```bash
cd frontend
npm install
npm run dev
```

Dashboard sur http://localhost:3000, explorateur sur /explorer.

### Couper la collecte automatique

Par défaut l'app collecte toute seule toutes les 20 minutes. Pour regarder
l'interface ou travailler sur le code sans qu'un passage parte derrière :

```bash
SCHEDULER_ENABLED=false uvicorn app.main:app --reload
```

Les routes `/api/admin/*` restent disponibles pour déclencher un passage à
la main.

## Déploiement (si tu veux une collecte permanente)

| Composant | Service | Pourquoi |
|---|---|---|
| Frontend (Next.js) | **Vercel** (plan Hobby, gratuit) | Fait pour Next.js, déploiement automatique depuis GitHub |
| Backend (FastAPI) | **Render** (plan Free) | Gratuit, mais se met en veille après 15 min d'inactivité (cold start ~30-60s au réveil) |
| Base de données | **Neon** (plan Free, 0,5 Go / 100h de calcul par mois) | Postgres serverless, gratuit en continu (pas d'expiration), scale-to-zero |
| Code | **GitHub** | Gratuit, connecte Vercel et Render en déploiement continu |
| Notifications | **Telegram** (bot gratuit) | — |

### 1. Pousser le code sur GitHub

Le dépôt git est déjà initialisé en local avec un premier commit. Il ne reste qu'à créer le repo distant et pousser :

```bash
# Crée d'abord un repo vide sur https://github.com/new (sans README ni .gitignore, ils existent déjà)
git remote add origin https://github.com/<ton-compte>/<ton-depot>.git
git branch -M main
git push -u origin main
```

### 2. Base de données — Neon

1. Créer un compte sur https://neon.tech (gratuit, pas de carte bancaire).
2. Créer un projet → copier la "Connection string" (commence par `postgresql://`).
3. La transformer en `postgresql+psycopg2://...` (même chaîne, juste le driver précisé) → c'est la valeur de `DATABASE_URL`.

### 3. Backend — Render

1. https://render.com → New → Blueprint → sélectionner ton repo GitHub (le fichier `render.yaml` à la racine est détecté automatiquement).
2. Renseigner les variables marquées `sync: false` dans le dashboard Render : `DATABASE_URL` (Neon), `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET`, et les autres clés optionnelles quand tu les auras.
3. Noter l'URL du service déployé (ex `https://<ton-service>.onrender.com`).

**Limite du plan gratuit** : le service s'endort après 15 min sans requête. Deux options :
- **Accepter la mise en veille** : configurer le secret GitHub `BACKEND_URL` (Settings → Secrets and variables → Actions) avec l'URL Render, le workflow `.github/workflows/trigger-check.yml` réveille le backend et lance un cycle de vérification toutes les 20 min, gratuitement, via GitHub Actions.
- **Payer ~7$/mois** (plan Starter Render) pour un backend toujours actif si tu préfères la simplicité.

### 4. Frontend — Vercel

1. https://vercel.com → New Project → importer le repo GitHub → Root Directory : `frontend`.
2. Ajouter la variable d'environnement `NEXT_PUBLIC_API_URL` = URL Render du backend.
3. Déployer. Chaque push sur `main` redéploie automatiquement.

## Outils/comptes gratuits nécessaires ou utiles

| Outil | Usage | Gratuit ? |
|---|---|---|
| [GitHub](https://github.com) | Héberger le code | Oui, illimité pour un compte perso |
| [Vercel](https://vercel.com) | Héberger le frontend | Oui (plan Hobby) |
| [Render](https://render.com) | Héberger le backend | Oui (plan Free, avec mise en veille — voir plus haut) |
| [Neon](https://neon.tech) | Base de données Postgres | Oui, en continu (0,5 Go / 100h calcul/mois) |
| [eBay Developer Program](https://developer.ebay.com) | Clé Browse API | Oui, compte gratuit |
| Telegram (@BotFather) | Bot de notification | Oui |
| [Anthropic Console](https://console.anthropic.com) | Analyse qualité photo + OCR | Payant à l'usage (quelques centimes/annonce analysée) — le reste de l'app fonctionne sans |
| [UptimeRobot](https://uptimerobot.com) | Alternative à GitHub Actions pour réveiller le backend Render | Oui (50 moniteurs, intervalle 5 min) |
| [cron-job.org](https://cron-job.org) | Autre alternative de cron externe, sans code | Oui |
| Docker Desktop / Python 3.11+ / Node.js 20+ / Git | Dev local | Oui, tout open-source |
| [DBeaver](https://dbeaver.io) | Inspecter la base Postgres/SQLite visuellement | Oui (édition communautaire) |
| [Postman](https://www.postman.com) ou juste `curl` | Tester les routes de l'API à la main | Oui |

**Rien dans cette liste ne coûte quelque chose pour démarrer**, à l'exception de l'API Anthropic (vision/OCR) qui est payante à l'usage — mais optionnelle : sans elle, le score de qualité se base uniquement sur l'analyse du texte de l'annonce.

## Ce qui reste à faire de ton côté

1. Créer les comptes ci-dessus et récupérer les clés (eBay obligatoire pour avoir des annonces eBay réelles ; le reste est optionnel).
2. Lancer en local, vérifier que `/api/health` répond et que le dashboard affiche (même vide au début).
3. Configurer eBay puis relancer un cycle via le bouton "Vérifier maintenant" du dashboard (ou `POST /api/admin/run-check-now`) et vérifier que des annonces apparaissent.
4. Si le scraper Vinted ne remonte rien : c'est probablement que la structure de page a changé depuis la vérification faite pendant le développement (voir les commentaires dans `vinted_scraper.py`) — copie-colle-moi un extrait du HTML obtenu et j'ajuste le parsing.
5. Déployer selon la section ci-dessus.

Je reste disponible pour déboguer à partir de tes retours (logs, erreurs, captures d'écran).

## Sécurité des dépendances (frontend)

Next.js 14.2.5, la version d'origine, traînait des failles classées
**critiques** (contournement d'autorisation dans le middleware,
empoisonnement de cache). Le projet est passé à **Next 14.2.35**, la
dernière version corrigée de la même série : c'est un correctif de patch,
sans changement d'API, et le build passe à l'identique.

`package-lock.json` est désormais versionné. Sans lui, Vercel et Render
réinstallaient les dépendances à leur guise à chaque déploiement, et rien
ne garantissait que la version corrigée soit bien celle déployée.

Il reste des alertes classées **hautes** sur `next` (`npm audit`). Elles ne
sont corrigées qu'à partir de Next 16, soit **deux versions majeures plus
loin** — une migration à part entière, pas une mise à jour. Je ne l'ai pas
faite d'office. Voici de quoi décider, sans enjoliver :

- **La plupart ne s'appliquent pas ici** : ni middleware, ni Server
  Actions, ni rewrites, ni i18n dans ce projet (vérifié). Restent trois
  pages qui lisent une API.
- **Sauf celles sur l'optimiseur d'images, qui elles s'appliquent** :
  `components/ListingCard.tsx` utilise `next/image`, et `next.config.js`
  déclare des `remotePatterns` pour les CDN Vinted et eBay ainsi que pour
  l'hôte des illustrations officielles. Les alertes
  visant l'Image Optimizer (déni de service, cache disque non borné) sont
  donc dans le périmètre réel du projet.
- **Ce qui les atténue** : ces trois-là visent les déploiements
  *auto-hébergés*. Sur Vercel, l'optimisation d'images tourne sur leur
  infrastructure, pas sur un serveur à toi qu'on pourrait saturer. Si un
  jour tu héberges le frontend ailleurs, elles redeviennent à prendre au
  sérieux.
- Enfin, le dashboard n'a **aucune authentification** et n'affiche aucune
  donnée personnelle : un contournement d'autorisation n'a rien à
  contourner.

Conclusion : rien d'urgent tant que le frontend est sur Vercel, à
reconsidérer si tu changes d'hébergeur.

À refaire de temps en temps, dans `frontend/` :

```bash
npm audit            # état des alertes
npm update next      # reste dans la série 14.x, sans risque de rupture
```
