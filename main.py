import argparse
import json
import logging
import os
import sys
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw
import tkinter as tk
from tkinter import messagebox, simpledialog

from winfspy import FileSystem, enable_debug_log
from winfspy.plumbing.win32_filetime import filetime_now

from ed_api import EcoleDirecteAPI
from edcloud_fs import EDCloudFileSystemOperations

APP_NAME = "EDCloud"
AUTHORIZE_URL = "https://betternotes.natchen.us.kg/authorize-edcloud"
ROAMING_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
CONFIG_FILE = ROAMING_DIR / "config.json"
LOG_FILE = ROAMING_DIR / "edcloud.log"

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config):
    ROAMING_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

def setup_logging(verbose=False):
    ROAMING_DIR.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

def _tk_root():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root


def ask_token():
    root = _tk_root()
    webbrowser.open(AUTHORIZE_URL)
    messagebox.showinfo(
        "EDCloud – Connexion requise",
        "Votre navigateur s'est ouvert sur la page d'autorisation.\n\n"
        "Connectez-vous a EcoleDirecte, copiez le token affiche "
        "puis cliquez OK.",
        parent=root,
    )
    token = simpledialog.askstring(
        "EDCloud – Coller le token",
        "Token :",
        parent=root,
    )
    root.destroy()
    return token.strip() if token else None


def show_error(message):
    root = _tk_root()
    messagebox.showerror("EDCloud – Erreur", message, parent=root)
    root.destroy()

def _make_icon_image():
    """Cree une icone 64x64 (E bleu sur fond transparent)."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([2, 2, size - 2, size - 2], fill=(30, 100, 210, 255))
    # Lettre « E »
    d.rectangle([16, 14, 20, 50], fill="white")
    d.rectangle([16, 14, 44, 20], fill="white")
    d.rectangle([16, 29, 38, 35], fill="white")
    d.rectangle([16, 44, 46, 50], fill="white")
    return img

def main():
    parser = argparse.ArgumentParser(description="EDCloud – Lecteur virtuel EcoleDirecte")
    parser.add_argument("-m", "--mount-point", default=None,
                        help="Lettre de lecteur (ex: E:)")
    parser.add_argument("-t", "--token", default=None, help="EdTokenRelogin")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("--reset-token", action="store_true",
                        help="Forcer la re-saisie du token")
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    if args.debug:
        enable_debug_log()

    config = load_config()

    if args.reset_token:
        config.pop("token", None)

    token = args.token or config.get("token")
    if not token:
        token = ask_token()
        if not token:
            sys.exit(0)
        config["token"] = token
        save_config(config)

    mount_point = args.mount_point or config.get("mount_point", "E:")

    api = EcoleDirecteAPI(token)

    logger.info("Chargement du cloud...")
    try:
        operations = EDCloudFileSystemOperations(api)
    except Exception as exc:
        logger.exception("Echec connexion cloud")
        show_error(f"Impossible de se connecter au cloud :\n{exc}")
        sys.exit(1)

    mount_path = Path(mount_point)
    is_drive = mount_path.parent == mount_path

    fs = FileSystem(
        str(mount_path),
        operations,
        sector_size=512,
        sectors_per_allocation_unit=1,
        volume_creation_time=filetime_now(),
        volume_serial_number=0,
        file_info_timeout=5000,
        case_sensitive_search=False,
        case_preserved_names=True,
        unicode_on_disk=True,
        persistent_acls=False,
        post_cleanup_when_modified_only=True,
        um_file_context_is_user_context2=True,
        file_system_name=APP_NAME,
        prefix="",
        debug=args.debug,
        reject_irp_prior_to_transact0=not is_drive,
    )

    fs.start()
    logger.info("Cloud monte sur %s", mount_point)

    label = operations._volume_info.get("volume_label", APP_NAME)
    tooltip = f"{label}  ({mount_point})"

    def _unmount(icon, _item):
        icon.stop()

    def _reconnect(icon, _item):
        icon.stop()
        config.pop("token", None)
        save_config(config)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    menu = pystray.Menu(
        pystray.MenuItem(tooltip, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Actualiser maintenant", lambda i, _: operations._load_cloud_tree()),
        pystray.MenuItem("Reconnecter (changer de token)", _reconnect),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Demonter et quitter", _unmount),
    )

    icon = pystray.Icon(APP_NAME, _make_icon_image(), tooltip, menu)

    try:
        icon.run()
    finally:
        logger.info("Demontage...")
        fs.stop()
        logger.info("Termine.")


if __name__ == "__main__":
    main()
