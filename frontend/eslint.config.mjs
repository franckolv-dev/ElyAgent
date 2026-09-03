// =============================================================================
// @project    ELY — Exactly Like You
// @file       frontend/eslint.config.mjs
// @brief      Flat config ESLint du frontend Next.js.
// @license    MIT
// =============================================================================
//
// ⚠️ CE QUE ÇA CORRIGE (02/09/2026) : `npm run lint` était MORT. Le script
// appelait `next lint`, retire de Next 16 (le depot est en 16.2.6), aucun
// fichier de config ESLint n'existait et eslint n'etait meme pas installe.
// Le job CI « Frontend » se limitait donc a `tsc --noEmit` : tout ce qu'un
// linter attrape (hook conditionnel, <img> sans alt, deps de useEffect)
// passait vert depuis des mois.
//
// ⚠️ POURQUOI DES RÈGLES EN « warn » : la config Next branchee sur les
// 25 000 lignes existantes sort 90 remarques. Une CI rouge des le premier jour
// n'est pas une CI : elle serait contournee. On garde donc TOUT le jeu de
// regles actif, mais les regles ci-dessous passent en avertissement — elles
// restent affichees a chaque run, elles ne bloquent pas. Le contrat : aucune
// AUTRE regle n'est desactivee, donc une nouvelle violation ecrite demain fait
// rougir la CI.
//
// ⚠️ ET SURTOUT — LA PORTÉE DE LA DÉGRADATION (revue 02/09) : une regle mise en
// « warn » globalement n'est pas mise en sourdine sur la dette existante, elle
// est ETEINTE PARTOUT, y compris dans le fichier qu'on ecrira demain. Ce n'est
// acceptable que pour les regles dont la dette est DIFFUSE (des dizaines de
// fichiers) : la restreindre nommement n'y voudrait rien dire. Des qu'une regle
// n'a qu'un ou deux fichiers fautifs, la degradation est bornee a ces
// fichiers-la par un bloc `files` — partout ailleurs elle reste bloquante.
//
// Meme raisonnement que le pin de ruff dans ci.yml : un linter qu'on ne peut
// pas satisfaire est un linter qu'on finit par ignorer.
import next from "eslint-config-next/core-web-vitals";

const config = [
  {
    ignores: ["**/node_modules/**", ".next/**", "out/**", "next-env.d.ts", "public/**"],
  },

  ...next,

  {
    // Dette DIFFUSE : ces regles sont degradees pour tout le depot, faute de
    // pouvoir nommer les fichiers fautifs sans recopier la moitie de `src/`.
    name: "ely/dette-diffuse",
    rules: {
      // 54 occurrences dans 34 fichiers. Regle du compilateur React (setState
      // dans un effet). Chaque cas demande de repenser le flux de donnees du
      // composant : c'est un chantier, pas un correctif de lint.
      "react-hooks/set-state-in-effect": "warn",
      // 14 occurrences dans 3 fichiers, toutes des apostrophes francaises dans
      // du JSX. Purement cosmetique.
      "react/no-unescaped-entities": "warn",
      // 4 occurrences dans 2 fichiers : mutation d'un objet issu des
      // props/state, et fonctions lues avant leur declaration dans
      // useVoiceConversation. Deux corrections de fond, pas un `files` de
      // complaisance.
      "react-hooks/immutability": "warn",
    },
  },

  {
    // Dette LOCALISÉE : un seul fichier fautif par regle, donc la degradation
    // s'arrete a ce fichier. Ailleurs — et dans tout fichier neuf — les deux
    // regles ci-dessous sont bloquantes.
    //
    // L'avatar 3D n'est pas corrige ici : `AvatarScene` lit une ref pendant le
    // rendu pour piloter une scene Three.js, et `AvatarPanel` definit ses
    // sous-composants dans son corps. Les deux touchent au cycle de rendu d'une
    // scene WebGL — ce sont des chantiers a part entiere.
    name: "ely/dette-avatar",
    files: [
      "src/components/avatar/AvatarPanel.tsx",
      "src/components/avatar/AvatarScene.tsx",
    ],
    rules: {
      // 6 occurrences, toutes AvatarPanel.tsx:559-564 : composants definis dans
      // le corps d'un autre composant (remontes a chaque rendu).
      "react-hooks/static-components": "warn",
      // 1 occurrence, AvatarScene.tsx:157 : lecture d'une ref pendant le rendu.
      "react-hooks/refs": "warn",
    },
  },
];

// ⛔ `react-hooks/rules-of-hooks` N'EST PAS DÉGRADÉE, et ne doit jamais l'etre.
// Elle etait passee en « warn » pour une unique violation —
// LiveBrowserPanel appelait `useCallback` apres un retour anticipe — ce qui
// eteignait le garde-fou sur les 25 000 lignes du depot pour epargner un
// fichier. Un ordre de hooks casse n'est pas du style : c'est un composant dont
// l'etat se decale silencieusement. Le composant a ete corrige (le hook est
// remonte au-dessus du `return null`), la regle est redevenue bloquante.

export default config;
