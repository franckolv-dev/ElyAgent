# Archive

Code retiré de la surface active du dépôt mais conservé dans l'historique. Rien
ici n'est compilé, testé ni déployé : aucune CI ne le regarde, aucun Dockerfile
ne le copie. Ce fichier explique pourquoi, pour qu'un retour en arrière soit une
décision et non une fouille.

---

## `mobile/` — applications Android et iOS

Archivées le **2026-09-02**.

### Ce que contient le dossier

| Chemin | Contenu | Dernier commit |
|---|---|---|
| `mobile/android/` | Application Android complète (Kotlin, Compose, Hilt, Room), 6 180 lignes de Kotlin | 2026-04-26 (`21aeae1`) |
| `mobile/android-racine/` | Second arbre Android, qui vivait à la **racine** du dépôt (`app/`, `gradle/`, `gradlew`, `build.gradle.kts`, `settings.gradle.kts`, `gradle.properties`), 2 667 lignes de Kotlin | 2026-03-25 (`14d9ae9`) |
| `mobile/ios/` | Application iOS (SwiftUI), 3 295 lignes de Swift | 2026-04-26 (`21aeae1`) |

### Pourquoi

**1. Usage mesuré à zéro.** Sur les cinq mois d'historique de production, aucune
des deux applications n'a produit un seul appel. Ce n'est pas un usage faible :
c'est l'absence d'usage.

**2. Deux arbres Android en double.** `android/` et l'arbre de la racine
déclaraient tous deux `rootProject.name = "ElyAgent"`, et **aucun des deux n'est
un sur-ensemble de l'autre** :

- présent seulement dans `android/` : `core/fcm/FcmTokenManager.kt`, le module
  `core/files/` (4 fichiers), `ConversationsApi.kt`, `LinkifiedText.kt`, et
  l'écran `ui/files/` (2 fichiers) ;
- présent seulement à la racine : `BaseUrlInterceptor.kt` (là où l'autre a
  `DynamicUrlInterceptor.kt`), `SkillUpdateRequest.kt`, et le composant
  `ui/components/avatar/` (2 fichiers).

Un mois sépare leurs derniers commits. Personne ne savait lequel faisait foi, et
une fusion demande un arbitrage fichier par fichier, pas un `rm -rf`.

**3. iOS ne compilait pas.** Aucun `.xcodeproj`, `.pbxproj`, `.xcworkspace` ni
`Package.swift` n'a jamais été commité. Les 3 295 lignes de Swift ne sont donc
adossées à aucun projet buildable : le dossier était du texte, pas un logiciel.

**4. Dérive du protocole WebSocket.** Le backend a évolué, pas les clients :

- `{"type": "done"}` est envoyé par `backend/app/routers/chat.py` depuis le
  **2026-05-23** (`ac1127e`) pour déverrouiller la saisie en fin de tour.
  Aucun des trois clients ne le connaît — leur champ de saisie resterait
  bloqué après chaque réponse.
- Sur `{"type": "error", ...}`, le backend met le texte dans la clé
  **`content`**. Les deux adaptateurs Kotlin lisent `json.optString("message")`
  et `WSMessage.swift` lit `json["message"]`. Résultat : bandeau d'erreur vide
  côté Android, « Erreur inconnue » côté iOS — jamais la vraie cause.
- `{"type": "stopped"}` est traité par iOS mais ignoré par les deux clients
  Android.

Les applications étaient donc doublement mortes : personne ne les lançait, et
elles n'auraient plus fonctionné correctement si quelqu'un l'avait fait.

### Ce qu'il faudrait faire pour les réveiller

Dans cet ordre, avant toute nouvelle fonctionnalité :

1. **Choisir un seul arbre Android.** Comparer `mobile/android/` et
   `mobile/android-racine/`, fusionner ce qui doit l'être, supprimer l'autre.
   Le second doit remonter au niveau de `mobile/` s'il gagne, pas revenir à la
   racine du dépôt : deux `settings.gradle.kts` concurrents sont la cause
   première de la confusion.
2. **Committer un projet Xcode** pour iOS (`.xcodeproj` ou `Package.swift`).
   Tant qu'il n'existe pas, le code Swift n'est pas vérifiable.
3. **Traiter `done` et `stopped`** dans les trois clients WebSocket, sinon la
   saisie reste verrouillée après la première réponse.
4. **Corriger la clé d'erreur** : lire `content`, pas `message`.
5. **Rejouer l'inventaire du protocole** contre `backend/app/routers/chat.py` et
   `voice.py` — les trois écarts listés plus haut sont ceux repérés le
   2026-09-02, pas une garantie d'exhaustivité pour une reprise ultérieure.
6. **Brancher une CI** (au minimum `./gradlew assembleDebug`), sans quoi la
   dérive recommencera au premier commit backend suivant.

### Revenir en arrière

L'historique est intact : les fichiers ont été déplacés avec `git mv`, donc
`git log --follow` sur n'importe lequel d'entre eux remonte avant l'archivage.
Pour restaurer un arbre, un `git mv` en sens inverse suffit ; penser alors à
remettre les motifs `.gitignore` correspondants (artefacts Gradle,
`local.properties`, `google-services.json`) sur le chemin restauré.
