# EDCloud

### **Monte ton cloud EcoleDirecte comme un vrai lecteur sur Windows, Linux et macOS.**

EDCloud expose le cloud EcoleDirecte en tant que lecteur/dossier virtuel dans l'explorateur de fichiers : lecture, écriture, glisser-déposer, renommage, création de dossiers inclus.

- **Windows** : utilise [WinFSP](https://winfsp.dev) pour monter un lecteur virtuel (ex. `E:`)
- **Linux** : utilise [FUSE](https://github.com/libfuse/libfuse) pour monter un dossier (ex. `~/EDCloud`)
- **macOS** : utilise [macFUSE](https://osxfuse.github.io/) pour monter un dossier (ex. `~/EDCloud`)

## Fonctionnalités

- Lecteur/dossier virtuel natif (drag & drop, copier-coller, tout fonctionne)
- Icône dans la barre système (system tray)
- Connexion guidée au premier lancement (ouverture du navigateur → coller le token)
- Credentials stockés dans un fichier de config local
- Auto-refresh de l'arborescence toutes les 30 secondes
- Notifications pour les erreurs d'extension de fichier
- Déplacement / copie de fichiers entre dossiers
- Logs dans le dossier de config

### Emplacement des fichiers de configuration

| OS | Chemin |
|----|--------|
| Windows | `%APPDATA%\EDCloud\` |
| Linux | `~/.config/EDCloud/` (ou `$XDG_CONFIG_HOME/EDCloud/`) |
| macOS | `~/Library/Application Support/EDCloud/` |

---

## Prérequis

### Windows

| Logiciel | Lien |
|----------|------|
| **WinFSP** (driver kernel, obligatoire) | [winfsp.dev/rel](https://winfsp.dev/rel/) |

### Linux

| Logiciel | Installation |
|----------|-------------|
| **FUSE** | `sudo apt install fuse` (Debian/Ubuntu) ou équivalent |

### macOS

| Logiciel | Lien |
|----------|------|
| **macFUSE** | [osxfuse.github.io](https://osxfuse.github.io/) |

### Pour builder (développeurs)

- Python 3.10 ou supérieur
- Windows : Microsoft Visual C++ Build Tools (requis par `winfspy`) — [télécharger](https://visualstudio.microsoft.com/visual-cpp-build-tools/)

---

## Installation rapide

### Windows

1. Installe [WinFSP](https://winfsp.dev/rel/)
2. Télécharge `EDCloud.exe` depuis la page [Releases](../../releases)
3. Lance `EDCloud.exe`
4. Au premier démarrage : le navigateur s'ouvre → connecte-toi à EcoleDirecte → copie le token → colle-le
5. Le lecteur `E:` apparaît dans l'Explorateur

### Linux / macOS

1. Installe FUSE (`sudo apt install fuse`) ou macFUSE
2. `pip install -r requirements.txt`
3. `python main.py`
4. Au premier démarrage : le navigateur s'ouvre → connecte-toi à EcoleDirecte → copie le token → colle-le
5. Le dossier `~/EDCloud` apparaît

> Pour changer de compte : clic droit sur l'icône systray → **Reconnecter (changer de token)**

---

## Utilisation en ligne de commande

```
python main.py [options]

Options :
  -m, --mount-point PATH    Point de montage (Windows: E:, Linux/Mac: ~/EDCloud)
  -t, --token TOKEN         Token (bypass la saisie graphique)
  -v, --verbose             Logs détaillés
  -d, --debug               Mode debug (Windows: WinFSP debug)
      --reset-token         Forcer la re-saisie du token
```

---

## Build depuis les sources

### Windows

```bat
git clone https://github.com/natchen007/ed-cloud.git
cd ed-cloud

pip install -r requirements.txt
pip install pyinstaller

build.bat
```

### Linux / macOS

```bash
git clone https://github.com/natchen007/ed-cloud.git
cd ed-cloud

pip install -r requirements.txt
pip install pyinstaller

chmod +x build.sh
./build.sh
```

