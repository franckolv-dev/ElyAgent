# Audit Technique V2 — ELY Agent

Ce rapport approfondit l'analyse de l'architecture multi-agent, du routage intelligent et de la sécurité du système après les récentes mises à jour.

---

## 1. Analyse de l'Architecture Multi-Agent

### ✅ Points Forts
- **Spécialisation des Sous-Agents** : Le découpage en domaines (`research`, `workspace`, `infra`, etc.) réduit drastiquement la taille des prompts système envoyés au LLM, ce qui améliore la précision et réduit les coûts.
- **Routage Hybride SLM/LLM** : L'utilisation d'un modèle local (Ollama) pour les tâches simples (score ≤ seuil) est une optimisation majeure. Cela garantit une latence minimale et une confidentialité totale pour les requêtes basiques.
- **Gestion des États** : L'isolation des messages par domaine dans `AgentState` évite que le contexte d'une recherche web ne vienne polluer une exécution de commande SSH complexe.

### ⚠️ Goulots d'étranglement potentiels
- **Latence du Router LLM** : Le `router_node` utilise un appel LLM pour classer la demande. Bien que nécessaire, cela ajoute une étape de latence avant même que l'agent spécialiste ne commence à travailler.
- **Séquențialité du Graphe** : Le passage `router → specialist → tools → specialist` est séquentiel. Si une requête complexe nécessite plusieurs outils de domaines différents, elle finit dans le nœud `general` qui est plus lourd.

---

## 2. Sécurité et Confidentialité

### ✅ Points Forts
- **Injection de Secrets (Vault)** : Le mécanisme de résolution des `vault://` dans le `tool_node` est exemplaire. Les secrets ne transitent jamais par le LLM, éliminant le risque de mémorisation dans le Cloud.
- **Anonymisation PII** : Le `SecurityFilter` reste la pièce maîtresse, protégeant activement les données sensibles avant l'envoi aux API cloud.
- **HITL (Human-in-the-Loop)** : L'enregistrement automatique des outils de contrôle OS dans `ALWAYS_CRITICAL_TOOLS` garantit qu'aucune action destructive n'est prise sans accord.

### ⚠️ Risques Identifiés
- **Exposition des Logs Audit** : S'assurer que les logs d'audit (table `audit_logs`) ne stockent pas les résultats déchiffrés des outils utilisant le Vault.
- **Timeout du SLM** : En cas de timeout du modèle local (Ollama), le système bascule sur le LLM cloud. Si le message contenait des données sensibles non filtrées, elles pourraient fuiter.

---

## 3. Recommandations

### R1. Optimisation du Routage (Performance)
- **Action** : Implémenter un cache de routage basé sur les embeddings pour les requêtes répétitives.
- **Gain** : Éviter l'appel au `router_node` pour les commandes fréquentes (ex: "quel temps fait-il"), réduisant la latence de ~1-2 secondes.

### R2. Isolation des Credentials (Sécurité)
- **Action** : S'assurer que les `google_credentials` et les secrets du Vault sont explicitement effacés de l'objet `state` dès que le nœud d'outil a terminé son exécution.

### R3. Supervision de l'Usage (Coûts)
- **Action** : Ajouter un monitoring en temps réel des jetons consommés par sous-agent pour identifier quel domaine coûte le plus cher et optimiser son prompt.

---

## Conclusion

L'architecture V2 d'ELY est extrêmement mature. Le passage à un système multi-agent supervisé avec routage SLM/LLM place ELY au sommet des solutions d'agents autonomes en termes de **ratio performance/confidentialité**.
