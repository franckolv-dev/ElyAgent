# Installation de l'app Android ELY sur ton téléphone

Ce guide explique comment **construire l'APK** depuis ton Mac Studio, le **déposer sur Google Drive**, puis l'**installer** sur un Android personnel (ou de test) — sans passer par le Play Store.

> **Rappel** — l'APK n'est pas signé via un certificat Play Store, il faudra donc autoriser une source inconnue. C'est la méthode standard pour diffuser une build privée à un cercle de beta-testeurs.

---

## 0. Pré-requis (one-shot, à faire une fois)

### Sur le Mac Studio

- **Android Studio** (Electric Eel ou plus récent) — [télécharger](https://developer.android.com/studio)
  Lance-le une fois pour qu'il installe le SDK (`~/Library/Android/sdk`) et accepte les licences.
- **JDK 17** (Android Studio en embarque un — sinon `brew install openjdk@17`)
- Variable `ANDROID_HOME` pointée sur le SDK :

  ```bash
  # Ajouter dans ~/.zshrc
  export ANDROID_HOME="$HOME/Library/Android/sdk"
  export PATH="$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin"
  ```

- **google-services.json** — depuis la console Firebase du projet ELY (app `com.ely.agent`), à placer dans `android/app/google-services.json`. Le build ne démarre pas sans.

### Sur le téléphone Android

- Android 9 (API 28) ou plus récent — l'`applicationId` est `com.ely.agent`, `minSdk = 28`
- Un compte Google connecté (pour Drive)
- ~60 Mo d'espace libre

---

## 1. Générer un keystore de signature (une seule fois, à garder précieusement)

Sans keystore, l'APK release ne s'installera pas. **Conserve ce fichier** : si tu le perds, toute future mise à jour publiée sous la même signature sera cassée.

```bash
cd ~/Documents/projets/ELY/PhysicalAgent-master/android
keytool -genkey -v \
  -keystore ely-release.keystore \
  -alias ely \
  -keyalg RSA -keysize 2048 \
  -validity 10000
```

Réponds aux questions (nom, organisation…) et choisis deux mots de passe (keystore + alias — mets-les identiques pour simplifier).

> ⚠️ **Ne commite JAMAIS ce fichier sur GitHub.** Ajoute `android/ely-release.keystore` au `.gitignore` s'il n'y est pas déjà.

### Déclarer la signature dans Gradle

Crée (ou édite) `android/keystore.properties` :

```
storeFile=ely-release.keystore
storePassword=MOT_DE_PASSE
keyAlias=ely
keyPassword=MOT_DE_PASSE
```

Ouvre `android/app/build.gradle.kts` et ajoute, en début de `android { ... }`, juste avant `namespace = …` :

```kotlin
val keystoreProps = java.util.Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) load(f.inputStream())
}

signingConfigs {
    create("release") {
        storeFile = file(keystoreProps["storeFile"] as String? ?: "ely-release.keystore")
        storePassword = keystoreProps["storePassword"] as String?
        keyAlias = keystoreProps["keyAlias"] as String?
        keyPassword = keystoreProps["keyPassword"] as String?
    }
}
```

Puis dans le bloc `buildTypes { release { … } }` déjà présent, ajoute :

```kotlin
signingConfig = signingConfigs.getByName("release")
```

Commite ce changement de `build.gradle.kts` (mais **pas** `keystore.properties` ni le `.keystore` lui-même).

---

## 2. Construire l'APK release

Depuis la racine du projet :

```bash
cd android
./gradlew clean assembleRelease
```

Le premier build peut prendre 3–8 min (téléchargement des deps Gradle). Les suivants sont < 1 min.

L'APK est produit ici :

```
android/app/build/outputs/apk/release/app-release.apk
```

Renomme-le pour identifier la version :

```bash
cp app/build/outputs/apk/release/app-release.apk \
   ~/Desktop/ely-<version>-release.apk
```

### Alternative : build debug (plus rapide, pas de keystore requis)

Pour un cycle de test rapide sans passer par la signature release :

```bash
./gradlew assembleDebug
# APK : android/app/build/outputs/apk/debug/app-debug.apk
```

Un APK debug est **auto-signé** avec une clé de développement — il s'installe sur ton téléphone, mais ne peut pas être distribué publiquement.

---

## 3. Déposer l'APK sur Google Drive

1. Ouvre [drive.google.com](https://drive.google.com) sur le Mac.
2. Crée un dossier `ELY — Builds` (par exemple).
3. Glisse `ely-<version>-release.apk` dans ce dossier.
4. Clic droit sur le fichier → **Partager** → **Obtenir le lien** → **Tous les utilisateurs avec le lien** (rôle : *Lecteur*).
5. Copie le lien.

> Pour un vrai canal de beta-testeurs, préfère **Firebase App Distribution** (gratuit) ou **GitHub Releases** — Drive marche pour un cercle privé.

---

## 4. Installer l'APK sur le téléphone

### 4.1 Autoriser les sources inconnues (une seule fois)

**Android 9–10 :**
Paramètres → Applications & notifications → Avancé → Accès spécial aux apps → Installer des applis inconnues → *Chrome* (ou *Drive*) → *Autoriser*.

**Android 11+ :**
Paramètres → Apps → *Menu ⋮* → Accès spécial → Installer des apps inconnues → choisir **Drive** et **Chrome** → activer.

### 4.2 Télécharger

1. Ouvre **l'app Google Drive** sur le téléphone (ou colle le lien dans Chrome).
2. Navigue dans `ELY — Builds`, appuie sur `ely-<version>-release.apk`.
3. Menu ⋮ → **Télécharger**. Le fichier arrive dans `Downloads/`.

### 4.3 Installer

1. Ouvre l'app **Fichiers** (ou **Mes Fichiers** sur Samsung) → `Downloads` → tape sur `ely-<version>-release.apk`.
2. Android affiche un avertissement *"Ce type de fichier peut endommager votre appareil"* → **Installer quand même**.
3. Google Play Protect peut demander *"Envoyer l'app pour analyse"* → **Installer sans analyser** (c'est ta propre app).
4. L'installation dure ~10 s. Appuie sur **Ouvrir**.

### 4.4 Configurer au premier lancement

1. **URL du serveur** : `https://ely.catalogmaker.fr` (ou l'URL Cloudflare du Mac Studio).
2. Se connecter avec ton login/mot de passe.
3. Autoriser : **Notifications** (pour les HITL push), **Micro** (pour le voice mode).
4. Optionnel : activer la biométrie pour déverrouiller l'app.

### 4.5 Tester rapidement

- Envoyer un message "Bonjour Ely" → réponse visible dans le chat
- Envoyer "Crée un événement demain à 14h" → notification HITL → approuver depuis le téléphone
- Appuyer sur l'icône micro → dire "Quelle est la météo à Lyon ?"

---

## 5. Mettre à jour l'app plus tard

Chaque nouvelle version, bump le `versionCode` et `versionName` dans `android/app/build.gradle.kts` :

```kotlin
defaultConfig {
    applicationId = "com.ely.agent"
    versionCode = <valeur actuelle + 1>  // +1 à chaque release
    versionName = "<version lisible>"     // ex. 1.0.1
    // ...
}
```

Puis rebuild (`./gradlew assembleRelease`), redépose sur Drive, retélécharge sur le téléphone : Android détecte la même signature et propose **Mettre à jour** (tes données utilisateur sont conservées).

Si tu changes le keystore, l'app s'installe comme une nouvelle app (perte des préférences locales).

---

## 6. Check-list rapide avant chaque build

- [ ] `frontend/.env.local` et `android` pointent bien sur l'URL publique (`https://ely.catalogmaker.fr`) et **non** sur `localhost` ou une IP Tailscale
- [ ] `versionCode` incrémenté
- [ ] `google-services.json` à jour (si changement Firebase)
- [ ] Backend Mac Studio up (`make ps`)
- [ ] Test rapide de login + 1 message depuis le téléphone avant de diffuser

---

## 7. Dépannage

| Symptôme | Cause probable | Fix |
|---|---|---|
| `App not installed` après tap sur l'APK | Signature incompatible avec une install précédente | Désinstalle l'ancienne version avant |
| `Parse error` au moment d'installer | APK corrompu au transfert | Re-télécharger depuis Drive |
| L'app ne se connecte pas | URL backend incorrecte / CORS | Vérifier `https://ely.catalogmaker.fr/api/health` depuis Chrome sur le téléphone |
| Pas de notification HITL | FCM non reçu | Vérifier que `google-services.json` du client matche le projet Firebase côté backend |
| Build Gradle échoue — `SDK location not found` | `ANDROID_HOME` non défini ou `android/local.properties` absent | Créer `android/local.properties` avec `sdk.dir=/Users/franck/Library/Android/sdk` |
| Build Gradle échoue — `google-services.json missing` | Fichier Firebase non téléchargé | [Firebase console](https://console.firebase.google.com) → projet ELY → Android app → télécharger le JSON → `android/app/google-services.json` |

---

## 8. Passer à la distribution publique (plus tard)

Quand tu voudras sortir du cercle privé :

1. **Firebase App Distribution** — gratuit, gestion des beta-testeurs par email, distribue l'APK via un lien court + QR code
2. **GitHub Releases** — attacher l'APK au tag de la version, lien direct depuis le README
3. **Play Store** — nécessite un compte dev Google (25 $ one-shot), révision, et remplir la politique de confidentialité. Le plus visible mais aussi le plus contraignant
4. **F-Droid** — si tu acceptes la publication 100 % open-source, l'app apparaît dans le store alternatif préféré des Linuxiens

Pour le **lancement officiel**, le duo **GitHub Releases + lien Drive** suffit largement — c'est ce que font la plupart des projets OSS indépendants à ce stade.
