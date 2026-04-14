import logging
import time
import threading
from ctypes import windll, c_int, c_wchar_p
from datetime import datetime
from functools import wraps
from pathlib import PureWindowsPath

from winfspy import (
    BaseFileSystemOperations,
    FILE_ATTRIBUTE,
    CREATE_FILE_CREATE_OPTIONS,
    NTStatusObjectNameNotFound,
    NTStatusDirectoryNotEmpty,
    NTStatusNotADirectory,
    NTStatusObjectNameCollision,
    NTStatusAccessDenied,
    NTStatusEndOfFile,
)
from winfspy.plumbing.win32_filetime import filetime_now
from winfspy.plumbing.security_descriptor import SecurityDescriptor

logger = logging.getLogger(__name__)

DEFAULT_SDDL = "O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;WD)"

EPOCH_AS_FILETIME = 116444736000000000
HUNDREDS_OF_NS = 10000000


def _notify(title, message):
    def _show():
        try:
            windll.user32.MessageBoxW(0, c_wchar_p(message), c_wchar_p(title), 0x00000040 | 0x00040000)
        except Exception:
            pass
    threading.Thread(target=_show, daemon=True).start()


def _datetime_to_filetime(dt):
    if isinstance(dt, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                dt = datetime.strptime(dt, fmt)
                break
            except ValueError:
                continue
        else:
            return filetime_now()
    try:
        ts = int(dt.timestamp())
    except (AttributeError, OSError):
        return filetime_now()
    return ts * HUNDREDS_OF_NS + EPOCH_AS_FILETIME


def operation(fn):
    name = fn.__name__

    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        head = args[0] if args else None
        try:
            with self._thread_lock:
                result = fn(self, *args, **kwargs)
        except Exception as exc:
            logger.debug(" NOK | %-20s | %r | %r", name, head, exc)
            raise
        else:
            logger.debug("  OK | %-20s | %r", name, head)
            return result

    return wrapper

class CloudBaseObj:
    ALLOCATION_UNIT = 4096

    def __init__(self, path, attributes, security_descriptor,
                 cloud_id="", cloud_date=None, cloud_size=0, cloud_info=None):
        self.path = path
        self.attributes = attributes
        self.security_descriptor = security_descriptor
        self.cloud_id = cloud_id
        self.cloud_info = cloud_info or {}

        ft = _datetime_to_filetime(cloud_date) if cloud_date else filetime_now()
        self.creation_time = ft
        self.last_access_time = ft
        self.last_write_time = ft
        self.change_time = ft
        self.index_number = 0
        self.file_size = cloud_size

    @property
    def name(self):
        return self.path.name

    def get_file_info(self):
        return {
            "file_attributes": self.attributes,
            "allocation_size": self.allocation_size,
            "file_size": self.file_size,
            "creation_time": self.creation_time,
            "last_access_time": self.last_access_time,
            "last_write_time": self.last_write_time,
            "change_time": self.change_time,
            "index_number": self.index_number,
        }

    def __repr__(self):
        return f"{type(self).__name__}:{self.path}"


class CloudFileObj(CloudBaseObj):
    def __init__(self, path, attributes, security_descriptor,
                 cloud_id="", cloud_date=None, cloud_size=0, cloud_info=None):
        super().__init__(path, attributes, security_descriptor,
                         cloud_id, cloud_date, cloud_size, cloud_info)
        self.attributes |= FILE_ATTRIBUTE.FILE_ATTRIBUTE_ARCHIVE
        self._data = bytearray()
        self._content_loaded = False
        self.dirty = False

    @property
    def allocation_size(self):
        return len(self._data)

    def set_allocation_size(self, allocation_size):
        if allocation_size < len(self._data):
            self._data = self._data[:allocation_size]
        elif allocation_size > len(self._data):
            self._data += bytearray(allocation_size - len(self._data))
        self.file_size = min(self.file_size, len(self._data))

    def adapt_allocation_size(self, file_size):
        units = (file_size + self.ALLOCATION_UNIT - 1) // self.ALLOCATION_UNIT
        self.set_allocation_size(units * self.ALLOCATION_UNIT)

    def set_file_size(self, file_size):
        if file_size < self.file_size:
            self._data[file_size:self.file_size] = bytearray(self.file_size - file_size)
        if file_size > len(self._data):
            self.adapt_allocation_size(file_size)
        self.file_size = file_size

    def ensure_content(self, api):
        if self._content_loaded:
            return
        if self.cloud_id:
            try:
                logger.info("Telechargement: %s", self.name)
                raw = api.download_file(self.cloud_id)
                self._data = bytearray(raw)
                self.file_size = len(raw)
                self.adapt_allocation_size(self.file_size)
            except Exception:
                logger.exception("Echec telechargement %s", self.name)
                self._data = bytearray()
                self.file_size = 0
        self._content_loaded = True

    def read(self, offset, length):
        if offset >= self.file_size:
            raise NTStatusEndOfFile()
        end = min(self.file_size, offset + length)
        return bytes(self._data[offset:end])

    def write(self, buffer, offset, write_to_end_of_file):
        if write_to_end_of_file:
            offset = self.file_size
        end = offset + len(buffer)
        if end > self.file_size:
            self.set_file_size(end)
        self._data[offset:end] = buffer
        self.dirty = True
        return len(buffer)

    def constrained_write(self, buffer, offset):
        if offset >= self.file_size:
            return 0
        end = min(self.file_size, offset + len(buffer))
        transferred = end - offset
        self._data[offset:end] = buffer[:transferred]
        self.dirty = True
        return transferred

    def get_content_bytes(self):
        return bytes(self._data[:self.file_size])


class CloudFolderObj(CloudBaseObj):
    def __init__(self, path, attributes, security_descriptor,
                 cloud_id="", cloud_date=None, cloud_size=0, cloud_info=None):
        super().__init__(path, attributes, security_descriptor,
                         cloud_id, cloud_date, cloud_size, cloud_info)
        self.allocation_size = 0


class CloudOpenedObj:
    def __init__(self, file_obj):
        self.file_obj = file_obj

    def __repr__(self):
        return f"Opened:{self.file_obj.path}"

class EDCloudFileSystemOperations(BaseFileSystemOperations):

    def __init__(self, api, volume_label="EDCloud"):
        super().__init__()
        if len(volume_label) > 31:
            raise ValueError("volume_label doit faire 31 caracteres max")

        self.api = api
        self._thread_lock = threading.Lock()
        self._root_path = PureWindowsPath("/")
        self._sd = SecurityDescriptor.from_string(DEFAULT_SDDL)

        self._root_obj = CloudFolderObj(
            self._root_path,
            FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY,
            self._sd,
        )
        self._entries = {self._root_path: self._root_obj}

        self._volume_info = {
            "total_size": 2147483648,
            "free_size": 2147483648,
            "volume_label": volume_label,
        }

        self._last_refresh = 0
        self._refresh_cooldown = 30
        self._load_cloud_tree()

    def _load_cloud_tree(self):
        try:
            data = self.api.list_cloud()
            if isinstance(data, list):
                data = data[0]

            quota = data.get("quota", 5368709120)
            used = data.get("taille", 0)
            self._volume_info["total_size"] = quota
            self._volume_info["free_size"] = max(0, quota - used)

            if self._volume_info["volume_label"] == "EDCloud":
                owner = self._find_proprietaire(data.get("children", []))
                if owner:
                    prenom = owner.get("prenom", "")
                    nom = owner.get("nom", "")
                    label = f"ED {prenom} {nom}".strip()[:31]
                    if label:
                        self._volume_info["volume_label"] = label

            self._root_obj.cloud_id = data.get("id", "")
            self._root_obj.cloud_info = self._make_parent_node_info(data)

            dirty = {p: o for p, o in self._entries.items()
                     if isinstance(o, CloudFileObj) and o.dirty}

            self._entries = {self._root_path: self._root_obj}
            self._parse_children(self._root_path, data.get("children", []))

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
            child_path = parent_path / name
            is_dir = child["type"] == "folder"

            if is_dir:
                obj = CloudFolderObj(
                    child_path,
                    FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY,
                    self._sd,
                    cloud_id=child.get("id", ""),
                    cloud_date=child.get("date"),
                    cloud_size=child.get("taille", 0),
                    cloud_info=child,
                )
            else:
                obj = CloudFileObj(
                    child_path,
                    FILE_ATTRIBUTE.FILE_ATTRIBUTE_ARCHIVE,
                    self._sd,
                    cloud_id=child.get("id", ""),
                    cloud_date=child.get("date"),
                    cloud_size=child.get("taille", 0),
                    cloud_info=child,
                )

            self._entries[child_path] = obj

            if is_dir and "children" in child:
                self._parse_children(child_path, child["children"])

    def _get_node_api_info(self, obj):
        info = {
            "id": obj.cloud_id,
            "type": "folder" if isinstance(obj, CloudFolderObj) else "file",
            "libelle": obj.name if obj.path != self._root_path else "/",
            "date": obj.cloud_info.get("date", "") if obj.cloud_info else "",
            "taille": obj.file_size,
            "displayText": obj.name,
            "isLoaded": isinstance(obj, CloudFolderObj),
            "isTrash": False,
            "children": [],
            "readonly": False,
            "hidden": False,
        }
        if obj.cloud_info and "proprietaire" in obj.cloud_info:
            info["proprietaire"] = obj.cloud_info["proprietaire"]
        return info

    def _get_parent_folder_id(self, path):
        parent_path = path.parent
        if parent_path in self._entries:
            return self._entries[parent_path].cloud_id
        return self.api.get_root_folder_id()

    def _upload_if_dirty(self, file_obj):
        if not isinstance(file_obj, CloudFileObj) or not file_obj.dirty:
            return
        try:
            parent_id = self._get_parent_folder_id(file_obj.path)
            content = file_obj.get_content_bytes()
            logger.info("Upload: %s (%d octets)", file_obj.name, len(content))
            result = self.api.upload_file(parent_id, file_obj.name, content)
            file_obj.cloud_id = result.get("id", file_obj.cloud_id)
            file_obj.cloud_info = result
            file_obj.dirty = False
        except RuntimeError as exc:
            msg = str(exc)
            if "Extension" in msg or "extension" in msg:
                _notify("EDCloud", f"Extension non prise en charge :\n{file_obj.name}")
                file_obj.dirty = False
                logger.warning("Extension refusee: %s", file_obj.name)
            else:
                logger.exception("Echec upload %s", file_obj.name)
        except Exception:
            logger.exception("Echec upload %s", file_obj.name)

    @operation
    def get_volume_info(self):
        return self._volume_info

    @operation
    def set_volume_label(self, volume_label):
        self._volume_info["volume_label"] = volume_label

    @operation
    def get_security_by_name(self, file_name):
        file_name = PureWindowsPath(file_name)
        try:
            file_obj = self._entries[file_name]
        except KeyError:
            raise NTStatusObjectNameNotFound()
        return (
            file_obj.attributes,
            file_obj.security_descriptor.handle,
            file_obj.security_descriptor.size,
        )

    @operation
    def create(
        self,
        file_name,
        create_options,
        granted_access,
        file_attributes,
        security_descriptor,
        allocation_size,
    ):
        file_name = PureWindowsPath(file_name)

        try:
            parent_obj = self._entries[file_name.parent]
            if isinstance(parent_obj, CloudFileObj):
                raise NTStatusNotADirectory()
        except KeyError:
            raise NTStatusObjectNameNotFound()

        if file_name in self._entries:
            raise NTStatusObjectNameCollision()

        is_dir = bool(create_options & CREATE_FILE_CREATE_OPTIONS.FILE_DIRECTORY_FILE)

        if is_dir:
            try:
                parent_info = parent_obj.cloud_info
                if isinstance(parent_info, dict) and "type" not in parent_info:
                    parent_info = self._get_node_api_info(parent_obj)
                result = self.api.create_folder(parent_info, file_name.name)
            except Exception:
                logger.exception("Echec creation dossier %s", file_name.name)
                raise NTStatusAccessDenied()

            file_obj = CloudFolderObj(
                file_name,
                file_attributes | FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY,
                security_descriptor,
                cloud_id=result.get("id", ""),
                cloud_date=result.get("date"),
                cloud_info=result,
            )
        else:
            file_obj = CloudFileObj(
                file_name,
                file_attributes,
                security_descriptor,
            )
            file_obj._content_loaded = True
            file_obj.dirty = True

        self._entries[file_name] = file_obj
        return CloudOpenedObj(file_obj)

    @operation
    def get_security(self, file_context):
        return file_context.file_obj.security_descriptor

    @operation
    def set_security(self, file_context, security_information, modification_descriptor):
        new_descriptor = file_context.file_obj.security_descriptor.evolve(
            security_information, modification_descriptor
        )
        file_context.file_obj.security_descriptor = new_descriptor

    @operation
    def rename(self, file_context, file_name, new_file_name, replace_if_exists):
        file_name = PureWindowsPath(file_name)
        new_file_name = PureWindowsPath(new_file_name)

        try:
            file_obj = self._entries[file_name]
        except KeyError:
            raise NTStatusObjectNameNotFound()

        if new_file_name in self._entries:
            if new_file_name.name != self._entries[new_file_name].path.name:
                pass
            elif not replace_if_exists:
                raise NTStatusObjectNameCollision()
            elif isinstance(file_obj, CloudFolderObj):
                raise NTStatusAccessDenied()

        same_dir = file_name.parent == new_file_name.parent
        new_name = new_file_name.name

        try:
            node_info = self._get_node_api_info(file_obj)

            if same_dir:
                self.api.rename(node_info, new_name)
            else:
                dest_parent = new_file_name.parent
                if dest_parent not in self._entries:
                    raise NTStatusObjectNameNotFound()
                dest_obj = self._entries[dest_parent]
                dest_info = self._get_node_api_info(dest_obj)
                result = self.api.copy(dest_info, [node_info])
                self.api.delete_to_trash([node_info])
                if file_name.name != new_name:
                    new_cloud_id = None
                    for child in result.get("children", []):
                        if child.get("libelle") == file_name.name:
                            new_cloud_id = child.get("id")
                            break
                    if new_cloud_id:
                        moved_node = dict(node_info)
                        moved_node["id"] = new_cloud_id
                        moved_node["libelle"] = file_name.name
                        self.api.rename(moved_node, new_name)

        except RuntimeError as exc:
            msg = str(exc)
            if "Extension" in msg or "extension" in msg:
                _notify("EDCloud", f"Extension non prise en charge :\n{new_name}")
                logger.warning("Extension refusee: %s", new_name)
            else:
                logger.exception("Echec renommage/deplacement %s -> %s", file_name, new_file_name)
            raise NTStatusAccessDenied()
        except Exception:
            logger.exception("Echec renommage/deplacement %s -> %s", file_name, new_file_name)
            raise NTStatusAccessDenied()

        for entry_path in list(self._entries):
            try:
                relative = entry_path.relative_to(file_name)
                new_entry_path = new_file_name / relative
                entry = self._entries.pop(entry_path)
                entry.path = new_entry_path
                self._entries[new_entry_path] = entry
            except ValueError:
                continue

    @operation
    def open(self, file_name, create_options, granted_access):
        file_name = PureWindowsPath(file_name)
        try:
            file_obj = self._entries[file_name]
        except KeyError:
            raise NTStatusObjectNameNotFound()
        return CloudOpenedObj(file_obj)

    @operation
    def close(self, file_context):
        self._upload_if_dirty(file_context.file_obj)

    @operation
    def get_file_info(self, file_context):
        return file_context.file_obj.get_file_info()

    @operation
    def set_basic_info(
        self, file_context, file_attributes, creation_time,
        last_access_time, last_write_time, change_time, file_info,
    ):
        obj = file_context.file_obj
        if file_attributes != FILE_ATTRIBUTE.INVALID_FILE_ATTRIBUTES:
            obj.attributes = file_attributes
        if creation_time:
            obj.creation_time = creation_time
        if last_access_time:
            obj.last_access_time = last_access_time
        if last_write_time:
            obj.last_write_time = last_write_time
        if change_time:
            obj.change_time = change_time
        return obj.get_file_info()

    @operation
    def set_file_size(self, file_context, new_size, set_allocation_size):
        obj = file_context.file_obj
        if isinstance(obj, CloudFileObj):
            obj.ensure_content(self.api)
            if set_allocation_size:
                obj.set_allocation_size(new_size)
            else:
                obj.set_file_size(new_size)

    @operation
    def can_delete(self, file_context, file_name):
        file_name = PureWindowsPath(file_name)
        try:
            file_obj = self._entries[file_name]
        except KeyError:
            raise NTStatusObjectNameNotFound()

        if isinstance(file_obj, CloudFolderObj):
            for entry in self._entries:
                try:
                    if entry.relative_to(file_name).parts:
                        raise NTStatusDirectoryNotEmpty()
                except ValueError:
                    continue

    @operation
    def read(self, file_context, offset, length):
        obj = file_context.file_obj
        if isinstance(obj, CloudFileObj):
            obj.ensure_content(self.api)
            return obj.read(offset, length)
        raise NTStatusAccessDenied()

    @operation
    def write(self, file_context, buffer, offset, write_to_end_of_file, constrained_io):
        obj = file_context.file_obj
        if isinstance(obj, CloudFileObj):
            obj.ensure_content(self.api)
            if constrained_io:
                return obj.constrained_write(buffer, offset)
            return obj.write(buffer, offset, write_to_end_of_file)
        raise NTStatusAccessDenied()

    @operation
    def flush(self, file_context):
        if file_context is None:
            return
        self._upload_if_dirty(file_context.file_obj)

    @operation
    def cleanup(self, file_context, file_name, flags):
        FspCleanupDelete = 0x01
        FspCleanupSetAllocationSize = 0x02
        FspCleanupSetArchiveBit = 0x10
        FspCleanupSetLastAccessTime = 0x20
        FspCleanupSetLastWriteTime = 0x40
        FspCleanupSetChangeTime = 0x80

        obj = file_context.file_obj

        if flags & FspCleanupDelete:
            try:
                node_info = self._get_node_api_info(obj)
                self.api.delete_to_trash([node_info])
                logger.info("Supprime (corbeille): %s", obj.path)
            except Exception:
                logger.exception("Echec suppression %s", obj.path)

            file_name_path = PureWindowsPath(file_name) if file_name else obj.path
            to_remove = [p for p in self._entries if p == file_name_path or
                         self._is_child_of(p, file_name_path)]
            for p in to_remove:
                self._entries.pop(p, None)
            return

        if flags & FspCleanupSetAllocationSize:
            if isinstance(obj, CloudFileObj):
                obj.adapt_allocation_size(obj.file_size)

        if flags & FspCleanupSetArchiveBit and isinstance(obj, CloudFileObj):
            obj.attributes |= FILE_ATTRIBUTE.FILE_ATTRIBUTE_ARCHIVE

        if flags & FspCleanupSetLastAccessTime:
            obj.last_access_time = filetime_now()

        if flags & FspCleanupSetLastWriteTime:
            obj.last_write_time = filetime_now()

        if flags & FspCleanupSetChangeTime:
            obj.change_time = filetime_now()

    @operation
    def overwrite(self, file_context, file_attributes, replace_file_attributes, allocation_size):
        obj = file_context.file_obj
        if not isinstance(obj, CloudFileObj):
            raise NTStatusAccessDenied()

        file_attributes |= FILE_ATTRIBUTE.FILE_ATTRIBUTE_ARCHIVE
        if replace_file_attributes:
            obj.attributes = file_attributes
        else:
            obj.attributes |= file_attributes

        obj.set_allocation_size(allocation_size)
        obj.file_size = 0
        obj.dirty = True

        now = filetime_now()
        obj.last_access_time = now
        obj.last_write_time = now
        obj.change_time = now

    @operation
    def read_directory(self, file_context, marker):
        self._refresh_if_needed()
        obj = file_context.file_obj
        if isinstance(obj, CloudFileObj):
            raise NTStatusNotADirectory()

        entries = []

        if obj.path != self._root_path:
            parent_obj = self._entries.get(obj.path.parent, obj)
            entries.append({"file_name": ".", **obj.get_file_info()})
            entries.append({"file_name": "..", **parent_obj.get_file_info()})

        for entry_path, entry_obj in self._entries.items():
            try:
                relative = entry_path.relative_to(obj.path)
            except ValueError:
                continue
            if len(relative.parts) != 1:
                continue
            entries.append({"file_name": entry_path.name, **entry_obj.get_file_info()})

        entries.sort(key=lambda x: x["file_name"])

        if marker is None:
            return entries

        for i, entry in enumerate(entries):
            if entry["file_name"] == marker:
                return entries[i + 1:]

        return []

    @operation
    def get_dir_info_by_name(self, file_context, file_name):
        path = file_context.file_obj.path / file_name
        try:
            entry_obj = self._entries[path]
        except KeyError:
            raise NTStatusObjectNameNotFound()
        return {"file_name": file_name, **entry_obj.get_file_info()}

    @staticmethod
    def _is_child_of(path, parent):
        try:
            path.relative_to(parent)
            return path != parent
        except ValueError:
            return False
