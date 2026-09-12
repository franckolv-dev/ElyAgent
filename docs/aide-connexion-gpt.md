# Ely indique « Connexion GPT interrompue »

Cette alerte apparaît lorsqu’un appel via l’abonnement ChatGPT est refusé pour un problème d’authentification. Ely peut alors continuer avec un modèle de secours si le routage en prévoit un. La présence d’une réponse ne signifie donc pas que GPT fonctionne encore.

Un administrateur peut cliquer sur **Reconnecter GPT**. Ce lien ouvre **Paramètres → Modèles IA**, à la carte **OpenAI — Abonnement ChatGPT (Codex)**. La carte affiche **Reconnexion nécessaire** et permet d’importer une nouvelle connexion directement, sans supprimer le modèle ou changer son ordre dans le routage.

Sur le Mac, renouveler la connexion avec le programme Codex comme indiqué sur la carte, puis importer les nouvelles informations dans ce formulaire. Ces informations sont confidentielles : ne pas les coller dans le chat ni les envoyer à un autre utilisateur.

Après un import validé ou un appel GPT réussi, l’alerte disparaît. Les autres pages ouvertes actualisent leur état périodiquement, au plus tard au prochain contrôle lorsque la page est visible. Une ancienne conversation peut conserver temporairement son modèle de secours.

Pour un compte non administrateur, l’alerte demande de contacter un administrateur : la connexion à cet abonnement est gérée pour l’instance Ely.

Une limite de quota ou une panne temporaire du fournisseur ne déclenche pas cette demande de reconnexion. L’état affiché repose sur les appels réellement observés ; l’écran ne lance pas une demande payante à GPT pour vérifier la connexion à chaque affichage.
