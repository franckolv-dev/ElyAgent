/**
 * @project    ELY — Exactly Like You
 * @file       frontend/scripts/stamp-sw-version.test.mjs
 * @brief      La version du service worker ne doit plus dependre d'un geste humain.
 * @license    MIT
 *
 * CE QUE CE FICHIER EPINGLE (02/09).
 *
 * `public/sw.js` portait `const VERSION = "ely-sw-v48"` sous la consigne
 * « Bump this on any sw.js change ». Le gestionnaire `activate` ne purge les
 * anciens caches que si cette chaine change — et elle n'avait pas bouge depuis
 * quatorze commits frontend (4fb580a..HEAD sur frontend/). Un onglet qui revient
 * apres un deploiement se voyait donc servir, depuis le cache du service worker,
 * un document HTML qui reference des empreintes de chunks que la reconstruction
 * a supprimees : ChunkLoadError. Le garde `ChunkReloadGuard` + `lib/recover.ts`
 * rattrape la panne, mais au prix d'un ecran blanc et d'un rechargement dur a
 * CHAQUE deploiement.
 *
 * La consigne « bump this » n'est pas un mecanisme : c'est un rappel, et un
 * rappel s'oublie. La version est desormais reecrite au build a partir de
 * `.next/BUILD_ID` (frontend/Dockerfile, apres `npm run build`).
 *
 * Deux pieges que ces tests ferment :
 *   - le no-op silencieux : si la ligne marquee disparait de `sw.js`, le script
 *     doit ECHOUER, pas passer sans rien faire ;
 *   - l'oubli du branchement : le Dockerfile doit appeler le script, sinon
 *     l'image embarque la valeur de repli et le bug revient a l'identique.
 *
 * Lancer :  cd frontend && node --test scripts/stamp-sw-version.test.mjs
 */
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { stampServiceWorkerVersion } from "./stamp-sw-version.mjs";

const RACINE_FRONTEND = dirname(dirname(fileURLToPath(import.meta.url)));
const SW_REEL = join(RACINE_FRONTEND, "public", "sw.js");

// La marque est ecrite ici, et non importee du script : un pin qui reutilise la
// definition de ce qu'il verifie ne verifie rien.
const MOTIF_VERSION = /^const VERSION = "([^"\n]*)"; *\/\/ ely:build-stamp$/m;

const temporaires = [];

/** Fabrique un faux dossier `frontend/` : package.json, .next/BUILD_ID, public/sw.js. */
function faux_frontend({ buildId, version = "9.9.9", sw = null }) {
  const racine = mkdtempSync(join(tmpdir(), "ely-sw-"));
  temporaires.push(racine);
  writeFileSync(join(racine, "package.json"), JSON.stringify({ version }));
  mkdirSync(join(racine, "public"), { recursive: true });
  writeFileSync(join(racine, "public", "sw.js"), sw ?? readFileSync(SW_REEL, "utf8"));
  if (buildId !== undefined) {
    mkdirSync(join(racine, ".next"), { recursive: true });
    writeFileSync(join(racine, ".next", "BUILD_ID"), buildId);
  }
  return racine;
}

const lire_sw = (racine) => readFileSync(join(racine, "public", "sw.js"), "utf8");

test.after(() => {
  for (const chemin of temporaires) rmSync(chemin, { recursive: true, force: true });
});

test("test_le_service_worker_livre_porte_la_marque_du_build", () => {
  const source = readFileSync(SW_REEL, "utf8");
  const trouve = MOTIF_VERSION.exec(source);
  assert.ok(
    trouve,
    "public/sw.js ne porte plus la ligne marquee `ely:build-stamp` : le script "
      + "de build ne trouvera rien a reecrire et la version redeviendra un "
      + "geste humain.",
  );
  assert.notEqual(trouve[1], "", "la valeur de repli ne doit pas etre vide");
});

test("test_deux_builds_donnent_deux_versions_de_cache", () => {
  const premier = faux_frontend({ buildId: "aaaaaaaaaaaaaaaaaaaaa" });
  const second = faux_frontend({ buildId: "bbbbbbbbbbbbbbbbbbbbb" });

  const a = stampServiceWorkerVersion(premier);
  const b = stampServiceWorkerVersion(second);

  assert.notEqual(
    a.version,
    b.version,
    "deux builds distincts produisent la meme version de cache : le "
      + "gestionnaire `activate` ne purgera rien et l'onglet gardera son HTML "
      + "perime.",
  );
  assert.match(MOTIF_VERSION.exec(lire_sw(premier))[1], /aaaaaaaaaaaaaaaaaaaaa/);
  assert.match(MOTIF_VERSION.exec(lire_sw(second))[1], /bbbbbbbbbbbbbbbbbbbbb/);
  assert.notEqual(lire_sw(premier), lire_sw(second));
});

test("test_la_version_estampillee_nomme_la_version_du_paquet", () => {
  const racine = faux_frontend({ buildId: "ccccccccccccccccccccc", version: "2.5.0" });
  const resultat = stampServiceWorkerVersion(racine);
  assert.match(resultat.version, /^ely-sw-2\.5\.0-ccccccccccccccccccccc$/);
});

test("test_le_marquage_est_idempotent", () => {
  const racine = faux_frontend({ buildId: "ddddddddddddddddddddd" });

  const premier = stampServiceWorkerVersion(racine);
  const apres_un = lire_sw(racine);
  const deuxieme = stampServiceWorkerVersion(racine);

  assert.equal(premier.written, true, "le premier passage doit ecrire");
  assert.match(apres_un, /ddddddddddddddddddddd/);

  assert.equal(
    lire_sw(racine),
    apres_un,
    "reappliquer l'estampille change le fichier : les valeurs s'accumulent.",
  );
  assert.equal(deuxieme.written, false, "rien a reecrire, donc rien n'est ecrit");
});

test("test_sans_identifiant_de_build_le_fichier_n_est_pas_touche", () => {
  const racine = faux_frontend({ buildId: undefined });
  const avant = lire_sw(racine);

  assert.throws(
    () => stampServiceWorkerVersion(racine),
    /BUILD_ID/,
    "sans build, le script doit refuser bruyamment plutot que d'inventer une "
      + "version : c'est le seul moyen qu'un branchement casse se voie.",
  );
  assert.equal(lire_sw(racine), avant, "la valeur de repli en dur reste servie");
});

test("test_un_service_worker_sans_marque_fait_echouer_le_build", () => {
  const racine = faux_frontend({
    buildId: "eeeeeeeeeeeeeeeeeeeee",
    sw: 'const VERSION = "ely-sw-v48";\n',
  });
  assert.throws(
    () => stampServiceWorkerVersion(racine),
    /ely:build-stamp/,
    "une ligne marquee disparue doit rougir : sinon le script ne fait rien, en "
      + "silence, et le ChunkLoadError revient a chaque deploiement.",
  );
});

test("test_un_identifiant_biscornu_ne_casse_pas_le_fichier", () => {
  const racine = faux_frontend({ buildId: 'fff"; self.pwned = 1; //\n' });
  const avant = lire_sw(racine).split("\n").length;
  const resultat = stampServiceWorkerVersion(racine);
  const apres = lire_sw(racine);

  // Ce qui compte n'est pas que la chaine soit jolie, mais qu'elle ne puisse pas
  // sortir du litteral : ni guillemet, ni antislash, ni saut de ligne.
  assert.ok(!/["\\\n]/.test(resultat.version), `version non echappee : ${resultat.version}`);
  assert.ok(
    MOTIF_VERSION.test(apres),
    "le fichier reecrit doit rester une ligne marquee valide",
  );
  assert.equal(apres.split("\n").length, avant, "aucune ligne ajoutee");
});

test("test_le_build_docker_appelle_l_estampilleuse", () => {
  const dockerfile = readFileSync(join(RACINE_FRONTEND, "Dockerfile"), "utf8");
  const construction = dockerfile.indexOf("npm run build");
  const estampille = dockerfile.indexOf("scripts/stamp-sw-version.mjs");

  assert.notEqual(
    estampille,
    -1,
    "le Dockerfile n'appelle pas scripts/stamp-sw-version.mjs : l'image "
      + "embarquerait la valeur de repli, donc une version figee.",
  );
  assert.ok(
    construction !== -1 && estampille > construction,
    "l'estampille doit venir APRES `npm run build` : .next/BUILD_ID n'existe "
      + "pas avant.",
  );
});

test("test_le_script_est_bien_copie_dans_l_image", () => {
  const ignore = readFileSync(join(RACINE_FRONTEND, ".dockerignore"), "utf8");
  assert.ok(
    !/^\s*scripts\/?\s*$/m.test(ignore),
    ".dockerignore exclut scripts/ : l'appel du Dockerfile echouerait.",
  );
  assert.ok(existsSync(join(RACINE_FRONTEND, "scripts", "stamp-sw-version.mjs")));
});
