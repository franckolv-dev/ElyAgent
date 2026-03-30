# Spécification Technique : Coffre-fort de Secrets (Vault) Autonome

Cette fonctionnalité permet à ELY de stocker et d'utiliser des secrets (mots de passe, clés API, identifiants) de manière souveraine, sans dépendre de services tiers payants et en garantissant que les secrets ne sont jamais lus par le LLM cloud.

---

## 1. Principes Fondamentaux

- **Autonomie Totale** : Utilisation exclusive de bibliothèques open-source (`cryptography`) et stockage local.
- **Zéro Coût** : Pas d'abonnement à des gestionnaires de mots de passe cloud.
- **Confidentialité LLM** : Le LLM manipule des "labels" (ex: `netflix_pass`), mais le backend injecte la valeur réelle directement dans les outils (navigateur, SSH) sans que le LLM ne la voie.
- **Sécurité Locale** : Chiffrement AES-256-GCM avec dérivation de clé Argon2.

---

## 2. Architecture de Chiffrement

### Algorithmes
- **Chiffrement** : AES-256 en mode GCM (Galois/Counter Mode) pour garantir l'intégrité et la confidentialité.
- **Dérivation de Clé** : Argon2id pour transformer le "Mot de passe Maître" de l'utilisateur en une clé de chiffrement robuste, avec un *salt* unique.

### Gestion de la Clé Maître
- Le **Mot de passe Maître** n'est JAMAIS stocké en base de données.
- Au démarrage ou après un timeout, ELY demande à l'utilisateur de "déverrouiller" le coffre-fort.
- La clé dérivée est conservée uniquement en **mémoire vive (RAM)** du processus FastAPI et n'est jamais écrite sur le disque.

---

## 3. Schéma de Données (SQLAlchemy)

Fichier cible : `backend/app/models/vault.py`

```python
class UserSecret(Base):
    __tablename__ = "user_secrets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(100))  # ex: "github_token", "banque_password"
    
    # Données chiffrées
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    tag: Mapped[bytes] = mapped_column(LargeBinary)
    salt: Mapped[bytes] = mapped_column(LargeBinary)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
```

---

## 4. Flux de Confidentialité (Injected Secrets)

L'innovation majeure réside dans l'injection directe par le backend :

1. **Enregistrement** : L'utilisateur fournit le secret. Le backend le chiffre immédiatement.
2. **Découverte** : Le LLM demande "Quels secrets as-tu pour Netflix ?". Le backend répond "J'ai un secret nommé `netflix_account`".
3. **Action** : Le LLM appelle un outil spécialisé, par exemple :
   `browser_login(url="netflix.com", secret_label="netflix_account")`.
4. **Exécution** :
   - Le backend intercepte l'appel.
   - Il déchiffre `netflix_account` en interne.
   - Il utilise Playwright pour remplir les champs `user` et `password` sur la page.
   - **Résultat** : Le LLM reçoit un succès/échec, mais la chaîne de caractères du mot de passe n'est jamais apparue dans le prompt ou la réponse du LLM.

---

## 5. Nouveaux Outils (Tools) de l'Agent

| Outil | Description | Sécurité |
| :--- | :--- | :--- |
| `vault_store` | Enregistre un secret sous un label donné. | Chiffrement immédiat. |
| `vault_list` | Liste les labels disponibles pour l'utilisateur. | Ne montre jamais les valeurs. |
| `vault_delete` | Supprime définitivement un secret. | Action irréversible. |
| `vault_unlock` | Permet à l'utilisateur de saisir son mot de passe maître. | Input masqué en UI. |

---

## 6. Sécurité et Résilience

- **Verrouillage automatique** : La clé en RAM est effacée après X minutes d'inactivité.
- **Protection contre le brute-force** : Argon2 est configuré pour être coûteux en CPU/RAM, rendant le craquage local extrêmement lent.
- **Audit Log** : Chaque accès à un secret est consigné dans les logs d'audit (sans la valeur) : *"L'agent a utilisé le secret 'banque_id' pour l'outil browser_fill"*.

---

## 7. Avantages Stratégiques

Cette implémentation transforme ELY en un véritable **mandataire de confiance**. Elle résout le problème majeur des agents IA actuels qui, pour être utiles, demandent souvent des accès sensibles qu'ils finissent par mémoriser de manière non sécurisée dans leurs historiques de conversation cloud.
