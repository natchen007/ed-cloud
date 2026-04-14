# EDCloud

### **Monte ton cloud EcoleDirecte comme un vrai lecteur Windows.**

EDCloud utilise [WinFSP](https://winfsp.dev) pour exposer le cloud EcoleDirecte en tant que lecteur virtuel dans l'Explorateur de fichiers : lecture, écriture, glisser-déposer, renommage, création de dossiers inclus.

## Fonctionnalités

- Lecteur virtuel natif Windows (drag & drop, copier-coller, tout fonctionne)
- Icône dans la barre système (system tray)
- Connexion guidée au premier lancement (ouverture du navigateur → coller le token)
- Credentials stockés dans `%APPDATA%\EDCloud\config.json`
- Auto-refresh de l'arborescence toutes les 30 secondes
- Notifications Windows pour les erreurs d'extension de fichier
- Déplacement / copie de fichiers entre dossiers
- Logs dans `%APPDATA%\EDCloud\edcloud.log`

---

## Prérequis

### Sur la machine cible (exécution)

| Logiciel | Lien |
|----------|------|
| **WinFSP** (driver kernel, obligatoire) | [winfsp.dev/rel](https://winfsp.dev/rel/) |

> WinFSP doit être installé **avant** de lancer EDCloud.

### Pour builder (développeurs)

- Python 3.10 ou supérieur
- Microsoft Visual C++ Build Tools (requis par `winfspy`) — [télécharger](https://visualstudio.microsoft.com/visual-cpp-build-tools/)

---

## Installation rapide

1. Installe [WinFSP](https://winfsp.dev/rel/)
2. Télécharge `EDCloud.exe` depuis la page [Releases](../../releases)
3. Lance `EDCloud.exe`
4. Au premier démarrage : le navigateur s'ouvre sur la page d'autorisation → connecte-toi à EcoleDirecte → copie le token → colle-le dans la fenêtre qui s'affiche
5. Le lecteur `E:` apparaît dans l'Explorateur

> Pour changer de compte : clic droit sur l'icône systray → **Reconnecter (changer de token)**

---

## Utilisation en ligne de commande

```
EDCloud.exe [options]

Options :
  -m, --mount-point E:    Lettre de lecteur (défaut : E:)
  -t, --token TOKEN       Token (bypass la saisie graphique)
  -v, --verbose           Logs détaillés
  -d, --debug             Mode debug WinFSP
      --reset-token       Forcer la re-saisie du token
```

---

## Build depuis les sources

```bat
git clone https://github.com/TON_USER/EDCloud.git
cd EDCloud

pip install -r requirements.txt
pip install pyinstaller

build.bat
```

L'exe est généré dans `dist\EDCloud.exe`.

