/**
 * @project    ELY — Exactly Like You
 * @file       frontend/scripts/stamp-sw-version.mjs
 * @brief      Reecrit la version du service worker avec l'identifiant du build.
 * @license    MIT
 *
 * ⚠️ CE QUE ÇA CORRIGE (02/09) : `public/sw.js` portait
 * `const VERSION = "ely-sw-v48"` sous la consigne « Bump this on any sw.js
 * change ». Le gestionnaire `activate` ne purge les anciens caches que si cette
 * chaine change ; elle n'avait pas bouge depuis quatorze commits frontend. Un
 * onglet qui revenait apres un deploiement se voyait donc servir, depuis le
 * cache du service worker, un document HTML pointant vers des empreintes de
 * chunks que la reconstruction avait supprimees : ChunkLoadError, ecran blanc,
 * puis rechargement dur par `ChunkReloadGuard`. A chaque deploiement.
 *
 * Une consigne en commentaire n'est pas un mecanisme. La version est desormais
 * derivee de `.next/BUILD_ID`, l'identifiant que Next.js genere a chaque build
 * et dont il se sert lui-meme pour ranger `/_next/static/<buildId>/`. Il change
 * exactement quand un nouveau build existe, c'est-a-dire quand les empreintes
 * de chunks peuvent avoir change.
 *
 * Le script est appele par frontend/Dockerfile, APRES `npm run build` (avant, le
 * fichier n'existe pas) et AVANT que le stage runner ne copie `public/`.
 *
 * ⚠️ Il echoue bruyamment dans les deux cas ou il ne pourrait rien garantir :
 * pas de `.next/BUILD_ID`, ou plus de ligne marquee `ely:build-stamp` dans
 * `sw.js`. Un estampilleur qui ne trouve rien a estampiller et sort en 0
 * ramenerait le bug a l'identique, en silence.
 *
 * Le developpement local n'appelle pas ce script : `sw.js` garde sa valeur en
 * dur, qui reste un litteral valide, et `ServiceWorkerRegister` n'enregistre
 * de toute facon le service worker qu'en production.
 *
 * Usage :  cd frontend && node scripts/stamp-sw-version.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// La ligne reecrite. Le marqueur en fin de ligne rend la cible non ambigue et
// le remplacement idempotent.
const MARKER = /^(const VERSION = ")([^"\n]*)("; *\/\/ ely:build-stamp)$/m;

/** Ne garde que ce qui peut vivre dans un litteral JavaScript et dans une cle de cache. */
function sanitize(valeur) {
  return String(valeur).trim().replace(/[^A-Za-z0-9_.-]/g, "");
}

/**
 * Estampille `public/sw.js` de `frontendRoot` avec `ely-sw-<version>-<buildId>`.
 *
 * @param {string} frontendRoot racine du dossier `frontend/`
 * @returns {{written: boolean, version: string}} `written` est faux quand la
 *          valeur en place est deja la bonne (relance du meme build).
 */
export function stampServiceWorkerVersion(frontendRoot) {
  const cheminBuildId = join(frontendRoot, ".next", "BUILD_ID");
  let buildId;
  try {
    buildId = sanitize(readFileSync(cheminBuildId, "utf8"));
  } catch {
    throw new Error(
      `BUILD_ID introuvable (${cheminBuildId}) : lancer ce script APRES `
        + "`npm run build`. Rien n'a ete ecrit.",
    );
  }
  if (!buildId) {
    throw new Error(`BUILD_ID vide (${cheminBuildId}). Rien n'a ete ecrit.`);
  }

  const paquet = JSON.parse(readFileSync(join(frontendRoot, "package.json"), "utf8"));
  const version = `ely-sw-${sanitize(paquet.version || "0")}-${buildId}`;

  const cheminSw = join(frontendRoot, "public", "sw.js");
  const source = readFileSync(cheminSw, "utf8");
  const trouve = MARKER.exec(source);
  if (!trouve) {
    throw new Error(
      `${cheminSw} ne porte plus la ligne marquee \`ely:build-stamp\` : `
        + "impossible d'estampiller la version. Sans elle, le service worker "
        + "garderait une version figee et les caches ne seraient jamais purges.",
    );
  }
  if (trouve[2] === version) return { written: false, version };

  writeFileSync(cheminSw, source.replace(MARKER, `$1${version}$3`), "utf8");
  return { written: true, version };
}

// Point d'entree CLI : la racine est le parent de `scripts/`.
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const racine = dirname(dirname(fileURLToPath(import.meta.url)));
  const { written, version } = stampServiceWorkerVersion(racine);
  console.log(
    written
      ? `service worker estampille : ${version}`
      : `service worker deja a jour : ${version}`,
  );
}
