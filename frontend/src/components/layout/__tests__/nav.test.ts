/**
 * @project    ELY — Exactly Like You
 * @file       frontend/src/components/layout/__tests__/nav.test.ts
 * @brief      Aucune page livree ne doit rester injoignable.
 *
 * @author     Franck OLLIVIER <contact@agent-ely.fr>
 * @copyright  Copyright (c) 2025-2026 Franck OLLIVIER
 * @license    MIT
 *            https://opensource.org/licenses/MIT
 */

/**
 * ⚠️ CE QUE ÇA CORRIGE (02/09/2026) : deux routes etaient livrees en production
 * sans qu'aucune navigation n'y mene. `/arena` fonctionnait (6 matchs et 3
 * lignes de classement en base) mais son entree avait ete retiree de la barre
 * laterale ; sa cle de traduction `sidebar.navArena` est restee, orpheline,
 * dans les deux catalogues. `/avatar-test` etait un bac a sable de
 * developpement expedie tel quel.
 *
 * Rien ne signalait l'ecart : `tsc --noEmit` compile parfaitement une page que
 * personne ne peut atteindre. Le test compare donc les DEUX inventaires — les
 * dossiers de routes sur le disque et les liens de la nav — et exige que
 * chaque route non listee dans la nav soit justifiee explicitement ici.
 *
 * Il verifie aussi le sens inverse (un lien de nav vers une page supprimee) et
 * la parite fr/en des catalogues de traduction, qui etait exacte au moment ou
 * ce test a ete ecrit.
 *
 * ⚠️ RELECTURE 02/09/2026 : la premiere version aplatissait l'arbre sans
 * regarder le drapeau `admin`, si bien qu'une page enterree dans le groupe
 * ADMINISTRATEUR comptait comme « liee » pour tout le monde. `/arena` etait
 * exactement dans ce cas : ses cinq routes backend n'exigent qu'un utilisateur
 * connecte, mais la barre laterale ne montrait le lien qu'aux administrateurs
 * — le defaut d'origine n'etait corrige que pour eux, et ce test ne le voyait
 * pas. Il raisonne desormais en VISIBILITE : ce que voit un simple
 * utilisateur, et ce que l'administrateur voit en plus.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { NAV, isGroup, type NavLeaf } from "../nav";

const FRONTEND_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
const APP_DIR = join(FRONTEND_ROOT, "src", "app");

/**
 * Routes volontairement absentes de la barre laterale, avec la raison. Toute
 * addition ici est une decision, pas un oubli : c'est le point du test.
 */
const ROUTES_ATTEINTES_AUTREMENT: Record<string, string> = {
  "/": "redirection vers /chat ou /login selon la session",
  "/login": "pre-authentification, la barre laterale n'est pas montee",
  "/setup": "premier demarrage, /chat y redirige tant que la config manque",
  "/offline": "page de repli mise en cache par le service worker",
  "/missions/[id]": "detail dynamique, ouvert depuis /missions",
  "/settings/api-keys": "sous-page liee depuis /settings",
  "/settings/extension": "sous-page liee depuis /settings",
  "/settings/mcp": "sous-page liee depuis /admin, donc reservee aux admins",
};

/**
 * Pages que la barre laterale reserve deliberement aux administrateurs. Le
 * critere n'est pas le confort d'affichage mais l'API : ces pages pilotent
 * l'instance (comptes, cles, garde-fous, file de graduation) et leurs routes
 * backend exigent un administrateur. Une page dont l'API se contente d'un
 * utilisateur connecte n'a rien a faire ici : elle serait injoignable pour la
 * plupart des gens alors que le backend la leur ouvre.
 */
const ROUTES_RESERVEES_AUX_ADMINS: Record<string, string> = {
  "/admin": "administration de l'instance",
  "/security": "garde-fous et journal de securite",
  "/me/learning/candidates": "file de graduation des competences",
  "/me/learning/tool-gaps": "trous d'outillage remontes par l'agent",
  "/me/learning/incidents": "incidents de l'instance",
};

/** Chaque dossier portant un `page.tsx` est une route livree. */
function routesLivrees(): string[] {
  const trouvees: string[] = [];
  const descendre = (dossier: string, prefixe: string) => {
    for (const entree of readdirSync(dossier, { withFileTypes: true })) {
      if (!entree.isDirectory()) continue;
      if (entree.name.startsWith("_")) continue;
      const chemin = join(dossier, entree.name);
      const route = `${prefixe}/${entree.name}`;
      if (existsSync(join(chemin, "page.tsx"))) trouvees.push(route);
      descendre(chemin, route);
    }
  };
  if (existsSync(join(APP_DIR, "page.tsx"))) trouvees.push("/");
  descendre(APP_DIR, "");
  return trouvees.sort();
}

/**
 * Les liens qu'une session voit REELLEMENT, en reproduisant le filtrage de
 * `Sidebar.tsx` : un groupe marque `admin` disparait en entier, et dans un
 * groupe visible chaque enfant marque `admin` disparait aussi.
 */
function feuillesVisibles(admin: boolean): NavLeaf[] {
  return NAV.flatMap((entree) => {
    if (isGroup(entree)) {
      if (entree.admin && !admin) return [];
      return entree.children.filter((enfant) => admin || !enfant.admin);
    }
    return entree.admin && !admin ? [] : [entree];
  });
}

/** L'inventaire complet : ce que voit un administrateur. */
function feuilles(): NavLeaf[] {
  return feuillesVisibles(true);
}

function catalogue(langue: string): Record<string, unknown> {
  return JSON.parse(readFileSync(join(FRONTEND_ROOT, "messages", `${langue}.json`), "utf8"));
}

function clesAplaties(objet: Record<string, unknown>, prefixe = ""): string[] {
  return Object.entries(objet).flatMap(([cle, valeur]) => {
    const complete = prefixe ? `${prefixe}.${cle}` : cle;
    return valeur !== null && typeof valeur === "object"
      ? clesAplaties(valeur as Record<string, unknown>, complete)
      : [complete];
  });
}

describe("navigation laterale", () => {
  it("ne laisse aucune page livree hors de la navigation d'un simple utilisateur", () => {
    // LE pin de la relecture : un lien enterre sous ADMINISTRATEUR n'est pas
    // un lien pour la personne qui n'est pas administratrice.
    const vues = new Set(feuillesVisibles(false).map((f) => f.href));
    const orphelines = routesLivrees().filter(
      (route) =>
        !vues.has(route) &&
        !(route in ROUTES_ATTEINTES_AUTREMENT) &&
        !(route in ROUTES_RESERVEES_AUX_ADMINS),
    );
    expect(orphelines).toEqual([]);
  });

  it("ne laisse aucune page livree hors de la navigation d'un administrateur", () => {
    const vues = new Set(feuillesVisibles(true).map((f) => f.href));
    const orphelines = routesLivrees().filter(
      (route) => !vues.has(route) && !(route in ROUTES_ATTEINTES_AUTREMENT),
    );
    expect(orphelines).toEqual([]);
  });

  it("ne reserve aux administrateurs que les pages declarees comme telles", () => {
    // Le sens inverse : une page masquee aux non-admins sans figurer dans la
    // liste ci-dessus est un masquage subi, pas une decision.
    const vuesAdmin = feuillesVisibles(true).map((f) => f.href);
    const vuesSimple = new Set(feuillesVisibles(false).map((f) => f.href));
    const masqueesEnSilence = vuesAdmin.filter(
      (href) => !vuesSimple.has(href) && !(href in ROUTES_RESERVEES_AUX_ADMINS),
    );
    expect(masqueesEnSilence).toEqual([]);
  });

  it("montre bien a l'administrateur chaque page qui lui est reservee", () => {
    // Et une reserve qui ne masque plus rien est un mensonge a retirer.
    const vuesAdmin = new Set(feuillesVisibles(true).map((f) => f.href));
    const vuesSimple = new Set(feuillesVisibles(false).map((f) => f.href));
    for (const route of Object.keys(ROUTES_RESERVEES_AUX_ADMINS)) {
      expect(vuesAdmin.has(route), `${route} absente de la nav admin`).toBe(true);
      expect(vuesSimple.has(route), `${route} visible sans etre admin`).toBe(false);
    }
  });

  it("ne pointe vers aucune page absente du disque", () => {
    const livrees = new Set(routesLivrees());
    const cassees = feuilles()
      .map((f) => f.href)
      .filter((href) => !livrees.has(href));
    expect(cassees).toEqual([]);
  });

  it("n'annonce que des routes reellement atteintes autrement", () => {
    // Une exception qui survit a la suppression de sa page devient un mensonge.
    const livrees = new Set(routesLivrees());
    const perimees = Object.keys(ROUTES_ATTEINTES_AUTREMENT).filter((r) => !livrees.has(r));
    expect(perimees).toEqual([]);
  });
});

describe("catalogues de traduction", () => {
  it("traduit chaque libelle de la navigation en fr et en en", () => {
    const attendues = feuilles().map((f) => `sidebar.${f.labelKey}`);
    for (const langue of ["fr", "en"]) {
      const presentes = new Set(clesAplaties(catalogue(langue)));
      const manquantes = attendues.filter((cle) => !presentes.has(cle));
      expect(manquantes, `catalogue ${langue}`).toEqual([]);
    }
  });

  it("garde fr et en strictement paritaires", () => {
    const fr = clesAplaties(catalogue("fr")).sort();
    const en = clesAplaties(catalogue("en")).sort();
    expect(fr).toEqual(en);
  });
});
