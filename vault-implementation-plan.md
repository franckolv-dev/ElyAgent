# Plan d'Implémentation : Vault Interne ELY (Secrets Chiffrés)

Ce document détaille les étapes pour mettre en place un coffre-fort de secrets local et sécurisé au sein d'ELY, permettant l'utilisation d'identifiants sensibles sans fuite vers les LLM Cloud.

---

## 1. Architecture de Sécurité (Principes)

- **Isolation Stricte** : Le LLM ne voit que le "Label" du secret (ex: `ssh_prod_key`). Le déchiffrement et l'injection se font uniquement au niveau du backend (Python) lors de l'exécution de l'outil.
- **Chiffrement Local** : Utilisation de la bibliothèque `cryptography` (AES-256-GCM).
- **Clé Maître (Master Key)** : L'utilisateur définit un mot de passe maître au premier usage. Cette clé est dérivée via Argon2 et conservée uniquement en RAM (pas de stockage sur disque).

---

## 2. Étape 1 : Modèle de Données (SQLAlchemy)

Fichier : `backend/app/models/vault.py`

- `id` : UUID unique.
- `user_id` : Lien vers l'utilisateur propriétaire.
- `label` : Nom unique du secret (ex: "google_search_api").
- `encrypted_value` : Blob contenant le secret chiffré.
- `nonce` : IV unique pour AES-GCM.
- `tag` : Tag d'authentification pour garantir l'intégrité.
- `salt` : Sel utilisé pour la dérivation de la clé.

---

## 3. Étape 2 : Service de Chiffrement (Backend)

Fichier : `backend/app/services/vault_service.py`

- `unlock_vault(master_password)` : Dérive la clé et la stocke dans une variable de classe protégée (Singleton).
- `lock_vault()` : Efface la clé de la mémoire.
- `store_secret(user_id, label, value)` : Chiffre et enregistre.
- `get_secret(user_id, label)` : Déchiffre et retourne la valeur en clair (utilisé uniquement par les Tools).

---

## 4. Étape 3 : Intégration dans le Graphe de l'Agent

### Modification de `nodes.py` (Tool Node)
Actuellement, les outils reçoivent leurs arguments directement du LLM. Le `tool_node` doit être enrichi pour :
1. Détecter si un argument attend un secret (ex: argument nommé `secret_label`).
2. Appeler `vault_service.get_secret()` pour récupérer la valeur réelle.
3. Remplacer le label par la valeur réelle juste avant d'appeler `tool.ainvoke()`.

### Avantage
Le LLM n'a jamais connaissance du secret. Dans son historique, il ne verra que :
`ssh_execute(host="vps1", secret_label="vps1_password", command="ls")`

---

## 5. Étape 4 : Interface Utilisateur (Frontend)

### Gestion des Secrets
- Nouvelle page `/settings/vault` dans le frontend.
- Formulaire pour ajouter un secret : `Label` + `Valeur` (champ password).
- Liste des labels existants avec option de suppression.

### Déverrouillage
- Si l'agent a besoin d'un secret et que le Vault est verrouillé :
    - Envoyer un message WebSocket `type: "vault_locked"`.
    - Le frontend affiche une modale demandant le **Mot de Passe Maître**.

---

## 6. Étape 5 : Migration des Outils Existants

Plusieurs outils gagneraient à utiliser le Vault immédiatement :
- `ssh_manager` : Stockage des mots de passe et clés privées SSH.
- `google_auth` : Stockage des `client_secret` et `refresh_tokens`.
- `browser_skill` : Stockage des identifiants de sites (Netflix, Banque, etc.) pour l'outil `browser_fill`.

---

## 7. Sécurité & Risques (Points de vigilance)

- **Protection contre le brute-force local** : Utiliser un coût Argon2 élevé (paramètres mathématiques) pour ralentir les attaques si le fichier `cyberentity.db` est volé.

### 8. Détails techniques sur Argon2 (Sécurité gratuite et souveraine)

**Argon2id** est l'algorithme de dérivation de clé (KDF) de référence mondiale, lauréat de la *Password Hashing Competition*. Son utilisation est **totalement gratuite et open-source**.

Le terme "coût élevé" ne désigne pas un prix financier, mais une **configuration mathématique** visant à ralentir volontairement les tentatives de déchiffrement pour un processeur. Cela rend les attaques par "force brute" (tentatives massives de deviner le mot de passe maître) techniquement et électriquement impossibles pour un pirate.

#### Paramètres recommandés (Souveraineté Maximale) :
- **Memory Cost (RAM)** : Allouer ~64 Mo ou 128 Mo de mémoire vive par tentative. Cela empêche l'utilisation de puces spécialisées (ASIC/GPU) pour craquer le mot de passe.
- **Time Cost (Itérations)** : Faire plusieurs passages (ex: 3 ou 4) pour que le calcul prenne environ **0,5 à 1 seconde** sur le serveur. Ce délai est imperceptible pour l'utilisateur lors du déverrouillage, mais rédhibitoire pour un attaquant testant des millions de combinaisons.
- **Parallelism** : Utiliser plusieurs cœurs du processeur (ex: 4 threads) pour le calcul du hachage.

Cette approche garantit une **assurance mathématique** que vos secrets restent protégés, même en cas de vol physique de la base de données SQLite.
- **Fuite dans les logs** : S'assurer que les valeurs déchiffrées sont filtrées dans `logging` et ne sont jamais renvoyées dans les réponses `AIMessage` vers l'utilisateur (déjà géré par le `SecurityFilter` en théorie).
- **Zéro-Knowledge** : Rappeler à l'utilisateur que s'il perd son Mot de Passe Maître, ses secrets ELY sont définitivement perdus (pas de procédure de récupération possible sans compromettre la sécurité).
