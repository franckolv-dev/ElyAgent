# Release checklist

> À utiliser à chaque fois qu'un sprint passe de `⏳` à `✅` (livraison effective).
> But : éviter la désynchro silencieuse entre le code, le repo et le site public — qui
> a déjà fait passer le Sprint 1 livré pour un sprint « à faire » sur agent-ely.fr.

## 1. Côté repo

- [ ] `ROADMAP.md` : sprint marqué `✅ <Mois Année>` (et plus `⏳`)
- [ ] `ROADMAP.md` : section livrables effectifs détaillée (fichiers créés, tests ajoutés, validations)
- [ ] `ROADMAP.md` : résidus cosmétiques connus listés explicitement (transparence > sweep-sous-le-tapis)
- [ ] `CHANGELOG.md` : entrée datée avec sections Added / Fixed / Changed
- [ ] Tag git créé : `git tag vX.Y.Z && git push --tags`
- [ ] GitHub Release publiée à partir du tag (notes copiées du CHANGELOG)

## 2. Côté site agent-ely.fr (CRITIQUE — ne jamais oublier)

- [ ] `website/build/src/components/RoadmapPage.tsx` : `state: 'active'` → `state: 'done'` pour l'`sp*` correspondant
- [ ] `website/build/src/i18n/fr.ts` : `when: 'MOIS ANNEE'` → `when: '✅ MOIS ANNEE'`
- [ ] `website/build/src/i18n/en.ts` : idem (`✅ MONTH YEAR`)
- [ ] `website/build/src/i18n/fr.ts` + `en.ts` : `body` mis à jour pour refléter la livraison effective (mention de la version, des outils livrés, etc.)
- [ ] `npm run build` réussit sans warning
- [ ] `rsync -avz --delete dist/ bat-vps:/var/www/agent-ely.fr/public_html/`
- [ ] `bash website/scripts/smoke-test.sh` retourne 🎉 vert
- [ ] **Vérification visuelle sur https://agent-ely.fr/roadmap** que la pastille verte ✅ apparaît bien

## 3. Communication

- [ ] Si différenciation forte : draft Telegram/LinkedIn/YouTube prêt
- [ ] Demo screencast capturable en < 30 s (sinon : pas démontrable = pas marketable)

## 4. Hygiène

- [ ] Aucune désynchro entre `ROADMAP.md` (repo) et `i18n/*.ts` (site) — diff régulier conseillé
- [ ] Si nouveau sprint introduit côté site (ajout `sp*`), il doit AUSSI exister dans `ROADMAP.md` (et vice-versa)

---

*Cette checklist est née le 17 mai 2026 après avoir réalisé que le Sprint 1 (Memory recall) livré en v1.1.2 le 16 mai apparaissait encore comme « à faire » sur le site jusqu'au lendemain.*
