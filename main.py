import argparse
import json
import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path

if sys.platform.startswith("linux"):
    os.environ.setdefault("PYSTRAY_BACKEND", "xorg")

import pystray
from PIL import Image, ImageDraw

try:
    import tkinter as tk
    from tkinter import messagebox, simpledialog
    _HAS_TK = True
except ImportError:
    _HAS_TK = False

from ed_api import EcoleDirecteAPI

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

APP_NAME = "EDCloud"
AUTHORIZE_URL = "https://betternotes.natchen.us.kg/authorize-edcloud"


def _get_data_dir():
    if IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif IS_MACOS:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def _default_mount_point():
    if IS_WINDOWS:
        return "E:"
    return str(Path.home() / "EDCloud")


ROAMING_DIR = _get_data_dir()
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

def ask_token():
    webbrowser.open(AUTHORIZE_URL)
    if _HAS_TK:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
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
    else:
        print(f"Ouvrez ce lien dans votre navigateur :\n{AUTHORIZE_URL}")
        token = input("Collez le token ici : ").strip()
        return token if token else None


def show_error(message):
    if _HAS_TK:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror("EDCloud – Erreur", message, parent=root)
        root.destroy()
    else:
        print(f"ERREUR : {message}", file=sys.stderr)

def _make_icon_image():
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([2, 2, size - 2, size - 2], fill=(30, 100, 210, 255))
    d.rectangle([16, 14, 20, 50], fill="white")
    d.rectangle([16, 14, 44, 20], fill="white")
    d.rectangle([16, 29, 38, 35], fill="white")
    d.rectangle([16, 44, 46, 50], fill="white")
    return img

def main():
    parser = argparse.ArgumentParser(description="EDCloud – Lecteur virtuel EcoleDirecte")
    parser.add_argument("-m", "--mount-point", default=None,
                        help="Point de montage (ex: E: sur Windows, ~/EDCloud sur Linux/Mac)")
    parser.add_argument("-t", "--token", default=None, help="EdTokenRelogin")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("--reset-token", action="store_true",
                        help="Forcer la re-saisie du token")
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

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

    mount_point = args.mount_point or config.get("mount_point", _default_mount_point())

    api = EcoleDirecteAPI(token)
    logger.info("Chargement du cloud...")

    if IS_WINDOWS:
        _run_windows(api, mount_point, args, config, logger)
    else:
        _run_fuse(api, mount_point, args, config, logger)


def _run_windows(api, mount_point, args, config, logger):
    from winfspy import FileSystem, enable_debug_log
    from winfspy.plumbing.win32_filetime import filetime_now
    from edcloud_fs import EDCloudFileSystemOperations

    if args.debug:
        enable_debug_log()

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


def _run_fuse(api, mount_point, args, config, logger):
    from edcloud_fs_fuse import EDCloudFuseOperations, mount_fuse

    try:
        operations = EDCloudFuseOperations(api)
    except Exception as exc:
        logger.exception("Echec connexion cloud")
        show_error(f"Impossible de se connecter au cloud :\n{exc}")
        sys.exit(1)

    mount_path = Path(mount_point).expanduser().resolve()
    mount_path.mkdir(parents=True, exist_ok=True)
    mount_str = str(mount_path)

    logger.info("Cloud monte sur %s", mount_str)

    label = operations.volume_label or APP_NAME
    tooltip = f"{label}  ({mount_str})"

    fuse_thread = None
    fuse_stopped = threading.Event()

    def _start_fuse():
        try:
            mount_fuse(mount_str, operations, foreground=True)
        except Exception:
            logger.exception("Erreur FUSE")
        finally:
            fuse_stopped.set()

    def _unmount(icon, _item):
        import subprocess
        if sys.platform == "darwin":
            subprocess.run(["umount", mount_str], check=False)
        else:
            subprocess.run(["fusermount", "-u", mount_str], check=False)
        icon.stop()

    def _reconnect(icon, _item):
        _unmount(icon, _item)
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

    fuse_thread = threading.Thread(target=_start_fuse, daemon=True)
    fuse_thread.start()

    try:
        icon.run()
    finally:
        import subprocess
        if sys.platform == "darwin":
            subprocess.run(["umount", mount_str], check=False)
        else:
            subprocess.run(["fusermount", "-u", mount_str], check=False)
        logger.info("Termine.")


if __name__ == "__main__":
    main()
