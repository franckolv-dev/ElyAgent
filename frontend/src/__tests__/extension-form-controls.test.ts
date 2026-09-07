// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";

// 07/09/2026 — inscription SensCritique : l'extension remplissait les champs
// texte d'un formulaire React, mais cliquer sur une <option> ne changeait pas
// le <select>, et cliquer sur le libellé d'une case à cocher ne la cochait
// pas. Le formulaire répondait « Ce champ est obligatoire », et la mission a
// dû demander à l'utilisateur de finir à la main. Le script de contenu doit
// savoir remplir un select (par valeur ou par texte d'option), cocher ou
// décocher une case ou un bouton radio, et un clic sur une option ou un
// libellé doit atteindre le contrôle — avec les événements que React écoute.

const SCRIPT = readFileSync(
  join(__dirname, "..", "..", "..", "extension", "chrome", "src", "content", "content-script.js"),
  "utf-8",
);

type Handlers = Record<string, (payload: Record<string, unknown>) => Record<string, unknown>>;
let handlers: Handlers;

function evenements(el: Element): string[] {
  const vus: string[] = [];
  for (const nom of ["input", "change", "click"]) el.addEventListener(nom, () => vus.push(nom));
  return vus;
}

beforeAll(() => {
  (globalThis as unknown as { chrome: unknown }).chrome = {
    runtime: { onMessage: { addListener: () => undefined } },
  };
  new Function(SCRIPT)();
  handlers = (window as unknown as { __ely_handlers: Handlers }).__ely_handlers;
});

beforeEach(() => {
  document.body.innerHTML = `
    <form>
      <input data-testid="email" type="email" />
      <select name="gender">
        <option value="">Sélectionner</option>
        <option value="female">Femme</option>
        <option value="male">Homme</option>
      </select>
      <input type="checkbox" id="cgu" name="termsAndConditions" />
      <label for="cgu">J'accepte les conditions générales d'utilisation</label>
      <label id="wrap"><input type="checkbox" name="newsletter" /> Newsletter</label>
      <input type="radio" name="plan" value="free" id="free" />
      <input type="radio" name="plan" value="pro" id="pro" />
    </form>`;
});

describe("le script de contenu expose ses handlers", () => {
  it("pour les tests, sous window.__ely_handlers", () => {
    expect(typeof handlers.fill).toBe("function");
    expect(typeof handlers.click).toBe("function");
  });
});

describe("fill sur un select", () => {
  it("choisit par valeur et prévient React", () => {
    const select = document.querySelector("select")!;
    const vus = evenements(select);
    const res = handlers.fill({ selector: "select[name='gender']", value: "male" });
    expect(res.ok).toBe(true);
    expect((select as HTMLSelectElement).value).toBe("male");
    expect(res.value).toBe("male");
    expect(res.text).toBe("Homme");
    expect(vus).toContain("change");
  });

  it("choisit aussi par le texte visible de l'option", () => {
    const res = handlers.fill({ selector: "select[name='gender']", value: "Homme" });
    expect(res.ok).toBe(true);
    expect((document.querySelector("select") as HTMLSelectElement).value).toBe("male");
  });

  it("refuse une option qui n'existe pas en listant les choix", () => {
    const res = handlers.fill({ selector: "select[name='gender']", value: "Autre chose" });
    expect(res.ok).toBe(false);
    expect(String(res.options)).toContain("Homme");
  });
});

describe("fill sur une case à cocher ou un bouton radio", () => {
  it("coche avec true et prévient React", () => {
    const cgu = document.querySelector("#cgu") as HTMLInputElement;
    const vus = evenements(cgu);
    const res = handlers.fill({ selector: "#cgu", value: "true" });
    expect(res.ok).toBe(true);
    expect(cgu.checked).toBe(true);
    expect(res.checked).toBe(true);
    expect(vus).toContain("change");
  });

  it("décoche avec false", () => {
    const cgu = document.querySelector("#cgu") as HTMLInputElement;
    cgu.checked = true;
    const res = handlers.fill({ selector: "#cgu", value: "false" });
    expect(res.ok).toBe(true);
    expect(cgu.checked).toBe(false);
  });

  it("sélectionne un bouton radio", () => {
    const res = handlers.fill({ selector: "#pro", value: "true" });
    expect(res.ok).toBe(true);
    expect((document.querySelector("#pro") as HTMLInputElement).checked).toBe(true);
  });
});

describe("click atteint le contrôle", () => {
  it("sur une option : le select parent prend sa valeur", () => {
    const select = document.querySelector("select")!;
    const vus = evenements(select);
    const res = handlers.click({ selector: "select[name='gender'] option[value='male']" });
    expect(res.ok).toBe(true);
    expect((select as HTMLSelectElement).value).toBe("male");
    expect(vus).toContain("change");
  });

  it("sur un libellé for= : la case associée bascule", () => {
    const cgu = document.querySelector("#cgu") as HTMLInputElement;
    const vus = evenements(cgu);
    const res = handlers.click({ selector: "label[for='cgu']" });
    expect(res.ok).toBe(true);
    expect(cgu.checked).toBe(true);
    expect(res.checked).toBe(true);
    expect(vus).toContain("change");
  });

  it("sur un libellé qui enveloppe la case : idem", () => {
    const box = document.querySelector("input[name='newsletter']") as HTMLInputElement;
    handlers.click({ selector: "#wrap" });
    expect(box.checked).toBe(true);
  });

  it("un champ texte se remplit toujours comme avant", () => {
    const res = handlers.fill({ selector: "input[data-testid='email']", value: "a@b.fr" });
    expect(res.ok).toBe(true);
    expect((document.querySelector("input[data-testid='email']") as HTMLInputElement).value).toBe("a@b.fr");
    expect(res.value_length).toBe(6);
  });
});
