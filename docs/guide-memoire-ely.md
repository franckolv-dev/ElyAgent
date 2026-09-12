# Comprendre et gérer les souvenirs d’Ely

## Où voir ce qu’Ely retient ?

Ouvrez **Analyse → Mes mémoires**. Choisissez une famille : **Profil consolidé**, **Faits**, **Préférences**, **Règles**, **Conversations** ou **Erreurs et corrections**. Le profil consolidé rassemble des informations durables ; les conversations et les états d’exécution restent des souvenirs de situations passées.

## Pourquoi Ely utilise-t-elle certains souvenirs ?

Ouvrez **Utilisé pour cette réponse**. Dépliez une demande pour voir les informations préparées pour Ely, leur source, leur date, la raison de leur sélection et leur taille. Une sélection vide signifie qu’aucun souvenir n’a été retenu, par exemple pour un simple calcul. Le compteur de tokens est une mesure de taille indicative, pas un montant facturé.

Ely choisit un petit contexte à chaque demande. Changer de sujet dans une même conversation ne doit donc pas conserver les seuls souvenirs du premier sujet.

## Comment corriger une information ?

Cliquez sur **Corriger** à côté du souvenir. Modifiez **Information à retenir**, choisissez où cette information s’applique, puis cliquez sur **Enregistrer**. La correction devient la valeur courante. L’ancienne valeur peut encore servir à une question historique, par exemple « Quelle était mon ancienne adresse ? ».

## Comment réserver un souvenir à une mission ou un compte ?

Dans la fenêtre **Corriger un souvenir**, choisissez **Utiliser cette information**. Vous pouvez garder un usage personnel ou choisir une mission ou un compte Google existant. Un souvenir de mission ne doit pas s’appliquer automatiquement à une autre mission.

Pour utiliser un contexte propre à un compte, nommez-le explicitement : « Sur mon compte bureau, où vont les factures ? ». Ce choix ne change ni les connexions ni les autorisations du compte. Si plusieurs comptes sont possibles, précisez lequel utiliser.

## À quoi sert l’épinglage ?

Cochez **Prioritaire quand la demande est pertinente**. Le souvenir passe en priorité parmi les résultats utiles. L’épinglage ne force pas l’injection d’une information hors sujet dans toutes les réponses.

## Comment oublier un souvenir ?

Cliquez sur la corbeille **Oublier**, puis confirmez. Ely retire cette entrée et ses versions historiques. Les extraits conservés dans le journal de sélection sont invalidés. Oublier une entrée ne supprime pas toute la conversation originale ni tous les documents dans lesquels l’information pouvait également figurer : ces archives se gèrent dans leurs pages respectives.

## Comment Ely reprend-elle une mission ?

Ely relit son objectif et les accusés d’actions enregistrés. Une action confirmée et une action incertaine restent distinctes. Si Ely attend une vérification, ouvrez **Autonomie → Suivi**, consultez les preuves, vérifiez l’effet réel puis choisissez l’action adaptée. Elle ne doit pas répéter automatiquement une écriture simplement parce que son résultat est incertain.

## Faut-il rouvrir une conversation après une correction ?

Non. Le profil et les preuves sont relus pour les demandes suivantes. Les recherches réutilisent un petit cache invalidé lors des modifications. L’indexation de nouveaux faits et documents peut se poursuivre en arrière-plan ; le profil SQL reste consultable pendant cette indexation.

## Les anciens souvenirs sont-ils envoyés en entier aux modèles ?

Non. Ely conserve les sources localement et prépare un contexte court. Elle peut rechercher davantage de détails lorsque la demande le nécessite. Un petit modèle local aide à extraire des faits stables en arrière-plan ; il ne décide pas si une action a réellement réussi.
