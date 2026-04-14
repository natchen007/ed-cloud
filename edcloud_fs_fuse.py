import errno
import logging
import os
import stat
import threading
import time
from datetime import datetime

from fuse import FUSE, FuseOSError, Operations

logger = logging.getLogger(__name__)


def _notify(title, message):
    def _show():
        try:
            import subprocess
            import sys
            if sys.platform == "darwin":
                subprocess.run([
                    "osascript", "-e",
                    f'display notification "{message}" with title "{title}"'
                ], check=False)
            else:
                subprocess.run([
                    "notify-send", title, message
                ], check=False)
        except Exception:
            pass
    threading.Thread(target=_show, daemon=True).start()


def _parse_date(date_str):
    if not date_str:
        return time.time()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(date_str, fmt).timestamp()
        except ValueError:
            continue
    return time.time()


class CloudEntry:
    def __init__(self, name, is_dir, cloud_id="", cloud_date=None,
                 cloud_size=0, cloud_info=None):
        self.name = name
        self.is_dir = is_dir
        self.cloud_id = cloud_id
        self.cloud_info = cloud_info or {}
        self.cloud_size = cloud_size

        ts = _parse_date(cloud_date) if cloud_date else time.time()
        self.ctime = ts
        self.mtime = ts
        self.atime = ts

        self._data = bytearray()
        self._content_loaded = False
        self.dirty = False

    def ensure_content(self, api):
        if self._content_loaded or self.is_dir:
            return
        if self.cloud_id:
            try:
                logger.info("Telechargement: %s", self.name)
                raw = api.download_file(self.cloud_id)
                self._data = bytearray(raw)
                self.cloud_size = len(raw)
            except Exception:
                logger.exception("Echec telechargement %s", self.name)
                self._data = bytearray()
                self.cloud_size = 0
        self._content_loaded = True

    def get_content(self):
        return bytes(self._data[:self.cloud_size])

    def read(self, offset, length):
        if offset >= self.cloud_size:
            return b""
        end = min(self.cloud_size, offset + length)
        return bytes(self._data[offset:end])

    def write(self, data, offset):
        end = offset + len(data)
        if end > len(self._data):
            self._data.extend(bytearray(end - len(self._data)))
        self._data[offset:end] = data
        if end > self.cloud_size:
            self.cloud_size = end
        self.dirty = True
        self.mtime = time.time()
        return len(data)

    def truncate(self, length):
        if length < self.cloud_size:
            self._data[length:self.cloud_size] = bytearray(self.cloud_size - length)
        elif length > len(self._data):
            self._data.extend(bytearray(length - len(self._data)))
        self.cloud_size = length
        self.dirty = True
        self.mtime = time.time()


class EDCloudFuseOperations(Operations):

    def __init__(self, api, volume_label="EDCloud"):
        self.api = api
        self._lock = threading.Lock()
        self._volume_label = volume_label

        self._entries = {"/": CloudEntry("/", is_dir=True)}
        self._root_cloud_info = {}

        self._volume_total = 2147483648
        self._volume_free = 2147483648

        self._last_refresh = 0
        self._refresh_cooldown = 30

        self._load_cloud_tree()

    @property
    def volume_label(self):
        return self._volume_label

    def _load_cloud_tree(self):
        try:
            data = self.api.list_cloud()
            if isinstance(data, list):
                data = data[0]

            quota = data.get("quota", 5368709120)
            used = data.get("taille", 0)
            self._volume_total = quota
            self._volume_free = max(0, quota - used)

            if self._volume_label == "EDCloud":
                owner = self._find_proprietaire(data.get("children", []))
                if owner:
                    prenom = owner.get("prenom", "")
                    nom = owner.get("nom", "")
                    label = f"ED {prenom} {nom}".strip()[:31]
                    if label:
                        self._volume_label = label

            self._root_cloud_info = self._make_parent_node_info(data)

            root_entry = self._entries.get("/", CloudEntry("/", is_dir=True))
            root_entry.cloud_id = data.get("id", "")
            root_entry.cloud_info = self._root_cloud_info

            dirty = {p: e for p, e in self._entries.items()
                     if not e.is_dir and e.dirty}

            self._entries = {"/": root_entry}
            self._parse_children("/", data.get("children", []))
            self._entries.update(dirty)

            self._last_refresh = time.monotonic()
            logger.info("Arborescence chargee : %d entrees", len(self._entries))
        except Exception:
            logger.exception("Echec du chargement de l'arborescence cloud")

    def _find_proprietaire(self, children):
        for child in children:
            if "proprietaire" in child:
                return child["proprietaire"]
            sub = self._find_proprietaire(child.get("children", []))
            if sub:
                return sub
        return None

    def _refresh_if_needed(self):
        if time.monotonic() - self._last_refresh > self._refresh_cooldown:
            logger.info("Rafraichissement de l'arborescence...")
            self._load_cloud_tree()

    def _make_parent_node_info(self, data):
        return {
            "id": data.get("id", ""),
            "type": "folder",
            "libelle": data.get("libelle", "/"),
            "date": data.get("date", ""),
            "taille": data.get("taille", 0),
            "isLoaded": True,
            "isTrash": False,
            "quota": data.get("quota", 0),
            "children": [],
            "readonly": False,
            "hidden": False,
        }

    def _parse_children(self, parent_path, children):
        for child in children:
            if child.get("isTrash", False):
                continue
            name = child["libelle"]
            if parent_path == "/":
                child_path = "/" + name
            else:
                child_path = parent_path + "/" + name
            is_dir = child["type"] == "folder"

            entry = CloudEntry(
                name=name,
                is_dir=is_dir,
                cloud_id=child.get("id", ""),
                cloud_date=child.get("date"),
                cloud_size=child.get("taille", 0),
                cloud_info=child,
            )
            self._entries[child_path] = entry

            if is_dir and "children" in child:
                self._parse_children(child_path, child["children"])

    def _get_node_api_info(self, entry):
        info = {
            "id": entry.cloud_id,
            "type": "folder" if entry.is_dir else "file",
            "libelle": entry.name,
            "date": entry.cloud_info.get("date", "") if entry.cloud_info else "",
            "taille": entry.cloud_size,
            "displayText": entry.name,
            "isLoaded": entry.is_dir,
            "isTrash": False,
            "children": [],
            "readonly": False,
            "hidden": False,
        }
        if entry.cloud_info and "proprietaire" in entry.cloud_info:
            info["proprietaire"] = entry.cloud_info["proprietaire"]
        return info

    def _get_parent_path(self, path):
        if path == "/":
            return "/"
        parent = path.rsplit("/", 1)[0]
        return parent if parent else "/"

    def _upload_if_dirty(self, path, entry):
        if entry.is_dir or not entry.dirty:
            return
        try:
            parent_path = self._get_parent_path(path)
            parent = self._entries.get(parent_path)
            parent_id = parent.cloud_id if parent else ""
            content = entry.get_content()
            logger.info("Upload: %s (%d octets)", entry.name, len(content))
            result = self.api.upload_file(parent_id, entry.name, content)
            entry.cloud_id = result.get("id", entry.cloud_id)
            entry.cloud_info = result
            entry.dirty = False
        except RuntimeError as exc:
            msg = str(exc)
            if "extension" in msg.lower():
                _notify("EDCloud", f"Extension non prise en charge :\n{entry.name}")
                entry.dirty = False
                logger.warning("Extension refusee: %s", entry.name)
            else:
                logger.exception("Echec upload %s", entry.name)
        except Exception:
            logger.exception("Echec upload %s", entry.name)

    def getattr(self, path, fh=None):
        with self._lock:
            self._refresh_if_needed()
            entry = self._entries.get(path)
            if not entry:
                raise FuseOSError(errno.ENOENT)

            now = time.time()
            if entry.is_dir:
                mode = stat.S_IFDIR | 0o755
                size = 0
                nlink = 2
            else:
                mode = stat.S_IFREG | 0o644
                size = entry.cloud_size
                nlink = 1

            return {
                "st_mode": mode,
                "st_nlink": nlink,
                "st_size": size,
                "st_ctime": entry.ctime,
                "st_mtime": entry.mtime,
                "st_atime": entry.atime,
                "st_uid": os.getuid() if hasattr(os, "getuid") else 0,
                "st_gid": os.getgid() if hasattr(os, "getgid") else 0,
            }

    def readdir(self, path, fh):
        with self._lock:
            self._refresh_if_needed()
            entries = [".", ".."]
            prefix = path if path == "/" else path + "/"
            for entry_path, entry in self._entries.items():
                if entry_path == path:
                    continue
                if not entry_path.startswith(prefix):
                    continue
                remainder = entry_path[len(prefix):]
                if "/" not in remainder:
                    entries.append(remainder)
            return sorted(entries)

    def read(self, path, length, offset, fh):
        with self._lock:
            entry = self._entries.get(path)
            if not entry or entry.is_dir:
                raise FuseOSError(errno.ENOENT)
            entry.ensure_content(self.api)
            return entry.read(offset, length)

    def write(self, path, data, offset, fh):
        with self._lock:
            entry = self._entries.get(path)
            if not entry or entry.is_dir:
                raise FuseOSError(errno.ENOENT)
            entry.ensure_content(self.api)
            return entry.write(data, offset)

    def create(self, path, mode, fi=None):
        with self._lock:
            parent_path = self._get_parent_path(path)
            if parent_path not in self._entries:
                raise FuseOSError(errno.ENOENT)
            if path in self._entries:
                raise FuseOSError(errno.EEXIST)

            name = path.rsplit("/", 1)[-1]
            entry = CloudEntry(name=name, is_dir=False)
            entry._content_loaded = True
            entry.dirty = True
            self._entries[path] = entry
            return 0

    def mkdir(self, path, mode):
        with self._lock:
            parent_path = self._get_parent_path(path)
            parent = self._entries.get(parent_path)
            if not parent:
                raise FuseOSError(errno.ENOENT)
            if path in self._entries:
                raise FuseOSError(errno.EEXIST)

            name = path.rsplit("/", 1)[-1]
            try:
                parent_info = parent.cloud_info
                if isinstance(parent_info, dict) and "type" not in parent_info:
                    parent_info = self._get_node_api_info(parent)
                result = self.api.create_folder(parent_info, name)
            except Exception:
                logger.exception("Echec creation dossier %s", name)
                raise FuseOSError(errno.EACCES)

            entry = CloudEntry(
                name=name,
                is_dir=True,
                cloud_id=result.get("id", ""),
                cloud_date=result.get("date"),
                cloud_info=result,
            )
            self._entries[path] = entry

    def unlink(self, path):
        with self._lock:
            entry = self._entries.get(path)
            if not entry:
                raise FuseOSError(errno.ENOENT)

            try:
                node_info = self._get_node_api_info(entry)
                self.api.delete_to_trash([node_info])
                logger.info("Supprime (corbeille): %s", path)
            except Exception:
                logger.exception("Echec suppression %s", path)
                raise FuseOSError(errno.EACCES)

            self._entries.pop(path, None)

    def rmdir(self, path):
        with self._lock:
            entry = self._entries.get(path)
            if not entry:
                raise FuseOSError(errno.ENOENT)

            prefix = path + "/"
            for p in self._entries:
                if p.startswith(prefix):
                    raise FuseOSError(errno.ENOTEMPTY)

            try:
                node_info = self._get_node_api_info(entry)
                self.api.delete_to_trash([node_info])
                logger.info("Supprime (corbeille): %s", path)
            except Exception:
                logger.exception("Echec suppression %s", path)
                raise FuseOSError(errno.EACCES)

            self._entries.pop(path, None)

    def rename(self, old, new):
        with self._lock:
            entry = self._entries.get(old)
            if not entry:
                raise FuseOSError(errno.ENOENT)

            old_parent = self._get_parent_path(old)
            new_parent = self._get_parent_path(new)
            new_name = new.rsplit("/", 1)[-1]

            try:
                node_info = self._get_node_api_info(entry)

                if old_parent == new_parent:
                    self.api.rename(node_info, new_name)
                else:
                    dest_obj = self._entries.get(new_parent)
                    if not dest_obj:
                        raise FuseOSError(errno.ENOENT)
                    dest_info = self._get_node_api_info(dest_obj)
                    result = self.api.copy(dest_info, [node_info])
                    self.api.delete_to_trash([node_info])
                    if entry.name != new_name:
                        new_cloud_id = None
                        for child in result.get("children", []):
                            if child.get("libelle") == entry.name:
                                new_cloud_id = child.get("id")
                                break
                        if new_cloud_id:
                            moved_node = dict(node_info)
                            moved_node["id"] = new_cloud_id
                            moved_node["libelle"] = entry.name
                            self.api.rename(moved_node, new_name)
            except RuntimeError as exc:
                msg = str(exc)
                if "extension" in msg.lower():
                    _notify("EDCloud", f"Extension non prise en charge :\n{new_name}")
                    logger.warning("Extension refusee: %s", new_name)
                else:
                    logger.exception("Echec renommage/deplacement %s -> %s", old, new)
                raise FuseOSError(errno.EACCES)
            except FuseOSError:
                raise
            except Exception:
                logger.exception("Echec renommage/deplacement %s -> %s", old, new)
                raise FuseOSError(errno.EACCES)

            prefix = old + "/"
            to_move = [(p, e) for p, e in self._entries.items()
                       if p == old or p.startswith(prefix)]
            for p, e in to_move:
                self._entries.pop(p)
                if p == old:
                    new_path = new
                else:
                    new_path = new + p[len(old):]
                e.name = new_path.rsplit("/", 1)[-1]
                self._entries[new_path] = e

    def truncate(self, path, length, fh=None):
        with self._lock:
            entry = self._entries.get(path)
            if not entry or entry.is_dir:
                raise FuseOSError(errno.ENOENT)
            entry.ensure_content(self.api)
            entry.truncate(length)

    def flush(self, path, fh):
        with self._lock:
            entry = self._entries.get(path)
            if entry:
                self._upload_if_dirty(path, entry)
        return 0

    def release(self, path, fh):
        with self._lock:
            entry = self._entries.get(path)
            if entry:
                self._upload_if_dirty(path, entry)
        return 0

    def statfs(self, path):
        block_size = 4096
        total_blocks = self._volume_total // block_size
        free_blocks = self._volume_free // block_size
        return {
            "f_bsize": block_size,
            "f_frsize": block_size,
            "f_blocks": total_blocks,
            "f_bfree": free_blocks,
            "f_bavail": free_blocks,
            "f_files": len(self._entries),
            "f_ffree": 1000000,
            "f_favail": 1000000,
            "f_namemax": 255,
        }

    def chmod(self, path, mode):
        return 0

    def chown(self, path, uid, gid):
        return 0

    def utimens(self, path, times=None):
        with self._lock:
            entry = self._entries.get(path)
            if entry:
                now = time.time()
                if times:
                    entry.atime = times[0]
                    entry.mtime = times[1]
                else:
                    entry.atime = now
                    entry.mtime = now
        return 0


def mount_fuse(mount_point, operations, foreground=True):
    import sys
    kwargs = {
        "foreground": foreground,
        "nothreads": False,
        "allow_other": False,
    }
    if sys.platform == "darwin":
        kwargs["volname"] = operations.volume_label

    FUSE(operations, mount_point, **kwargs)
