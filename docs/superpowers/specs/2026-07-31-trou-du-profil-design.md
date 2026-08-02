# Le trou du profil — conception

> Écrit le 31/07/2026, après mesure. Validé par Franck section par section.
> Tous les chiffres cités ont été comptés, pas estimés.

## Le problème

Le catalogue d'outils envoyé au modèle à chaque tour est choisi par un
**profil** : une liste blanche nommée, portée par la conversation
(`conversations.toolset_profile`). Un seul profil existe, `default`.

Mesuré le 30/07 :

```
outils enregistrés            206
profil « default »             87   (84 déclarés + 3 unis dynamiquement)
injoignables depuis le profil 119
```

**Seize familles entières sont absentes** — Sheets (0/9), Docs (0/7), PDF (0/4),
Maps (0/4), YouTube, QR codes, `os_*`, `system_*`, `trainer_*`, `watchdog_*`,
WhatsApp, plus `ssh`, `analyze`, `briefing`, `python`, `telegram`, `delegate`.
Et de grosses partielles : Agenda 3/10, Contacts 1/8, Tasks 2/8, Gmail 12/21.

Concrètement : une conversation qui a un profil ne peut ni ouvrir un tableur, ni
lire un PDF — y compris `pdf_to_docx`, construit en juillet.

### Pourquoi, et ce que ça n'est pas

Le ménage du 29-30/07 n'y est pour rien : comparée avant et après le chantier,
la liste blanche n'a subi **qu'un seul retrait**, `orchestrate`, et aucun ajout.

Le profil a été **conçu comme un sous-ensemble volontaire**. Son en-tête le
dit : *« a hand-curated list of ~25-35 tool names […] covers ~80 % of everyday
workflows »*. Les familles absentes lui sont **antérieures** — `docs_*`,
`maps_*`, `youtube_*`, `qrcode_*` datent de mars 2026, le profil du 7 mai.

Depuis, la liste n'a reçu que des **correctifs réactifs**, un outil à la fois,
quand quelqu'un butait dessus en production : #37, #43, #106, #143, #257, #267.
Six en trois mois, jamais de revue d'ensemble. C'est ainsi qu'une liste prévue
pour 25-35 noms en atteint 84 tout en oubliant des familles entières.

Le filet de sécurité prévu existait — `find_tool`, première entrée de la liste,
avec son commentaire d'origine : *« the safety net: lets the model pull in any
catalog tool it doesn't currently see »*. Il se trompait une fois sur deux
jusqu'à #302.

## La décision, et sa preuve

**Le catalogue complet est bindé à chaque tour.** Décidé après mesure, pas
avant.

Un banc A/B (`bench/run_catalog_ab.py`) compare, à demande identique et modèle
identique, le choix d'outil avec 87 outils puis avec 206. Deux moitiés :
20 demandes dont le bon outil est **déjà** au profil (mesure le risque), 15 dont
il est **absent** (mesure le gain). Trois passes par cas.

**Règle de décision posée AVANT de lancer** — sans quoi un résultat mitigé se
lit toujours comme un succès :

> on bascule si la moitié RÉGRESSION ne perd pas plus d'un cas
> ET si la moitié TROU progresse nettement.

Résultat sur trois modèles :

```
                   gpt-5.6-terra      gpt-5.6-sol        kimi-k3
                 profil  complet   profil  complet   profil  complet
RÉGRESSION       91,7 %  91,7 %    91,7 %  88,3 %    91,5 %  84,7 %
TROU              0,0 %  86,7 %     0,0 %  86,7 %     0,0 %  82,8 %
VERDICT          BASCULER          BASCULER          NE PAS BASCULER
```

L'hypothèse d'origine — « le modèle apprend son catalogue par cœur », donc
l'élargir dégraderait — **n'est pas confirmée**. Sur Terra la justesse est
identique ; sur Sol elle perd deux appels sur soixante.

⚠️ **Kimi échoue à la règle, d'un seul appel**, sur un échantillon amputé de
16 % par la saturation de Moonshot (33 appels exclus, 5 cas du trou sans aucune
donnée). Il n'est pas en tête du tier C dans la configuration retenue.

⚠️ **Les deux seuls trous non réparés sur Sol** sont `calendar_check_availability`
et `calendar_create_meet_event` — les deux cas dont la vérité terrain est
discutable : lister les événements répond légitimement à « suis-je libre », et
organiser une visio avec quelqu'un exige d'abord de chercher son adresse. Hors
ces deux-là, Sol répare **13 trous sur 13**.

⚠️ **Le gain n'est pas « Ely y arrive enfin ».** Avec 87 outils, le modèle a
appelé `find_tool` dans 8 des 15 cas du trou : il ne renonçait pas, il
consultait l'annuaire. Le gain réel est qu'il y arrive **du premier coup** au
lieu de deux ou trois tours — ce qui compte, la latence étant le vrai problème
d'usage.

## Ce qui change

Le pipeline de branchement compte quatre étages. Un seul bouge.

```
1. SÉLECTION   profil (87) OU filtre à mots-clés     →  tout le catalogue
2. + UNION     outils nommés dans le prompt (auto)   →  devient un no-op, retiré
3. − RETRAIT   Playwright si l'extension est connectée   inchangé
4. − RETRAIT   outils réservés au tier C si tier ≠ C      inchangé
```

Les deux branches de l'étage 1 convergent : la branche disparaît.
L'étage 2 ne peut plus rien unir à un ensemble complet.

### Le mécanisme de profil est CONSERVÉ

```python
_PROFILES: dict[str, tuple[str, ...] | None] = {
    "default": None,      # None = tout le catalogue
}
```

`resolve_profile_tools` rend `all_tools` quand le profil vaut `None`, est vide,
ou est inconnu.

**Pourquoi le garder** — trois raisons mesurées :

1. **Cinq surfaces l'appellent** (`chat`, voix, Telegram, Slack, Discord). Le
   supprimer imposerait de les réécrire toutes pour un lot dont le but est de
   brancher plus d'outils.
2. **Le champ porte un second sens.** `usage_instrumentation` s'en sert pour
   attribuer l'architecture d'un tour : `if toolset_profile: return ARCH_MONO`.
   Sa docstring dit *« Ne devine jamais »* — supprimer le champ ferait basculer
   **tous** les tours en `unknown` et ferait perdre la distinction mono-agent
   que le banc V2 avait servi à établir.
3. **Le défaut n'était pas le mécanisme** mais une liste tenue à la main. Une
   valeur calculée ne peut pas décrocher.

Objection assumée : garder un mécanisme dont l'unique entrée signifie « tout »
est de la structure pour rien. C'est vrai. Elle pèse une quinzaine de lignes,
elle évite de toucher cinq surfaces, et elle préserve un signal de mesure. S'il
n'a toujours servi à rien dans trois mois, on le supprimera **avec la mesure
pour le justifier**.

## Le cas limite traité : `browser_search_images`

Le catalogue complet fait entrer des outils Playwright que le profil n'avait
pas. Un filtre existe (étage 3) : quand l'extension Chrome est connectée, les
outils Playwright serveur sont retirés, parce qu'ils tournent dans un contexte
**sans cookies** qui atterrit sur des pages de connexion.

Ce filtre nomme 7 outils. Le catalogue complet en introduit un huitième :

```
browser_search_images    Playwright serveur    absent du filtre
```

**Décision : ne PAS le filtrer**, et écrire la raison sur place.

Il cherche sur Google Images, qui ne demande aucune connexion — l'absence de
cookies ne le gêne pas. Et c'est le **seul** outil qui sait chercher une image :
le filtrer supprimerait la capacité dès que l'extension est connectée. Le filtre
vise les tâches qui exigent la session de l'utilisateur ; celle-ci n'en a pas
besoin.

Sans commentaire explicite, le prochain lecteur « corrigera » cette absence.

## Ce qui ne pose PAS de problème, contrairement à ce qui a été craint

**Les fenêtres de contexte.** Le catalogue complet pèse **34 805 tokens** contre
13 707 aujourd'hui. Vérifié : chaque instance déclare sa fenêtre, et c'est cette
valeur qui fait foi.

```
gemma-4-E4B (tête du tier IMAGE)    65 536
qwen3.5-9b                          65 568
gpt-5.6-sol / terra              1 000 000
```

⚠️ Deux mesures intermédiaires ont fait croire à un défaut inexistant : la
première interrogeait un **nom court** sans préfixe (repli à 8 192), la seconde
tournait dans un **processus neuf sans charger les réglages** (repli sur la
table codée en dur, 32 768). Les deux pièges sont documentés dans la mémoire du
projet. **Charger `load_llm_settings_from_db()` avant de lire une config.**

**Le coût en tokens.** Sur un forfait, +21 098 tokens par tour ne coûtent pas
d'argent, et représentent 3,5 % d'une fenêtre d'un million. L'entrée moyenne
réelle est déjà de 115 416 tokens.

**Le cache de préfixe.** Il relit 40 à 49 % de l'entrée depuis le 27/07. Un
catalogue complet mais **figé** reste cacheable — il devient même plus stable
qu'avant, puisqu'il est identique pour toutes les conversations. C'est le
filtrage **dynamique** par tour qui l'aurait cassé, pas celui-ci.

## Les tests

Rouge d'abord.

**Ce qui doit changer**

- `resolve_profile_tools("default", …)` rend les 206 (87 aujourd'hui)
- `resolve_profile_tools("", …)` rend les 206 (passait au filtre à mots-clés)
- les 16 familles absentes sont joignables — `sheets_*`, `docs_*`, `pdf_*`,
  `maps_*`, `contacts_*`…
- sans profil, le branchement donne le **même** résultat qu'avec

**Ce qui ne doit pas changer — les pins anti-régression**

- **un profil restrictif restreint encore.** C'est le pin qui compte : sans
  lui, on « réussirait » le lot en rendant `resolve_profile_tools` équivalent à
  `return all_tools`, et le mécanisme serait mort sans que rien ne rougisse ;
- le filtre extension retire bien les 7 outils Playwright quand l'extension est
  connectée ;
- `browser_search_images` **reste bindé** — la dispense, épinglée pour qu'on ne
  la « corrige » pas ;
- le filtre par tier reste branché ;
- `toolset_profile` continue d'être persisté, sinon les statistiques
  d'architecture passent en `unknown`.

## Le retour arrière

Une entrée de dictionnaire : `"default": None` redevient le tuple des 84 noms.
Pas de migration, pas de schéma, pas de données touchées.

Le lot est **réversible par configuration**, pas par `git revert` — c'est la
propriété recherchée en conservant le mécanisme.

## Ce qui suit, dans un lot séparé

Une fois le catalogue complet branché, `filter_tools_by_query` et
`tools_named_in_text` n'ont plus d'appelant. `tool_filter.py` — le module que le
cadrage du ménage voulait supprimer, et qu'il a fallu défendre parce qu'il
portait alors **71 % des tours** — devient enfin supprimable.

Dans un lot suivant : un lot change le branchement, l'autre retire ce qui n'a
plus de rôle. Diff lisible, retour arrière simple.

---

## Ce que l'implémentation a corrigé dans cette conception (#323, 02/08)

Deux affirmations de ce document étaient **fausses**, découvertes en écrivant le
lot. Elles sont laissées telles quelles ci-dessus et corrigées ici : une
conception qu'on réécrit après coup ne s'apprend plus.

### ⛔ « Les fenêtres de contexte ne posent PAS de problème » — faux

Le document compare le poids du catalogue à la fenêtre d'un million de
`gpt-5.6-sol`. Il n'a jamais fait le ratio pour le tier qui tourne réellement
sur le modèle **local** :

```
catalogue complet    ~61 000 tokens de descriptions (schémas compris)
tête du tier IMAGE   gemma-4-E4B, fenêtre déclarée 65 536
                     → 93 % de la fenêtre, avant le premier mot de conversation
```

Le banc A/B n'a d'ailleurs mesuré que des têtes de tier COMPLEX. Étendre le
catalogue complet à un tier qui ne peut pas le porter aurait été livrer une
régression **non mesurée** — exactement ce que ce document reproche à la liste
tenue à la main.

👉 D'où le profil **`compact`** : la liste de 84, branchée hors tier COMPLEX.
C'est le **premier usage réel** du mécanisme que la section « Le mécanisme de
profil est CONSERVÉ » défendait sans lui connaître d'emploi. L'objection
« garder un mécanisme dont l'unique entrée signifie *tout* est de la structure
pour rien » est donc levée par la mesure, pas par l'argument.

### ⛔ « L'étage 1 est le seul qui bouge » — incomplet

Un drapeau **baissé** doit continuer d'écarter ses outils. Ceux du Reversible
Journal ne sont branchés que si `reversible_journal_enabled` est ON ; rendre
`all_tools` tel quel les aurait rendus appelables drapeau éteint.

⚠️ **C'est un test existant qui l'a signalé, pas moi.**
`test_resolve_profile_unions_reversible_dynamically` est passé au rouge. Sans
lui, le lot partait avec une porte ouverte.

### Les tests de l'ancien contrat

Vingt pins interrogeaient l'appartenance à un tuple tenu à la main. **Aucun n'a
été supprimé** : ils ont été réancrés sur la propriété qu'ils gardaient.

- « Ely doit pouvoir supprimer ses tâches planifiées » → **joignabilité**, au
  lieu d'appartenance à une liste ;
- « le profil restreint » → réancré sur **`compact`**, où la restriction vit ;
- « un serveur MCP supprimé ne reste pas branché » → l'ancien pin le vérifiait
  **dans** `resolve_profile_tools`, en lui passant une liste construite à la
  main. Le vrai garde-fou est en amont : le nœud passe `registry.all_tools`, le
  registre **vivant**. Remplacé par deux pins à la bonne couche — la fonction ne
  rend jamais rien qui ne lui ait été donné, et le nœud lit bien le registre.
