import logging
import mimetypes
import threading
import requests

logger = logging.getLogger(__name__)
BASE_URL = "https://betternotes.natchen.us.kg/ed-endpoints-onelogin/v2/cloud"

class EcoleDirecteAPI:
    def __init__(self, token, type_compte="E"):
        self.token = token
        self.type_compte = type_compte
        self.session = requests.Session()
        self._lock = threading.Lock()

    def _get(self, endpoint, extra_params=None):
        params = {"token": self.token, "typeCompte": self.type_compte}
        if extra_params:
            params.update(extra_params)
        with self._lock:
            resp = self.session.get(f"{BASE_URL}/{endpoint}", params=params)
            result = resp.json()
            if result.get("code") != 200:
                raise RuntimeError(
                    f"Erreur API {endpoint} (code {result.get('code')}): {result.get('message', '')}"
                )
            return result["data"]

    def _post_json(self, endpoint, payload, extra_params=None):
        params = {"token": self.token, "typeCompte": self.type_compte}
        if extra_params:
            params.update(extra_params)
        with self._lock:
            resp = self.session.post(
                f"{BASE_URL}/{endpoint}", params=params, json=payload
            )
            result = resp.json()
            if result.get("code") != 200:
                raise RuntimeError(
                    f"Erreur API {endpoint} (code {result.get('code')}): {result.get('message', '')}"
                )
            return result["data"]

    def list_cloud(self):
        return self._get("liste")

    def download_file(self, file_id):
        params = {"token": self.token, "fichierId": file_id}
        with self._lock:
            resp = self.session.post(f"{BASE_URL}/download", params=params)
            ct = resp.headers.get("content-type", "")
            if ct.startswith("application/json"):
                result = resp.json()
                if result.get("code") != 200:
                    raise RuntimeError(f"Echec download: {result.get('message', '')}")
            return resp.content

    def upload_file(self, dest_folder_id, filename, content):
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        params = {"token": self.token, "dest": dest_folder_id}
        with self._lock:
            resp = self.session.post(
                f"{BASE_URL}/upload", params=params,
                files={"file": (filename, content, mime_type)},
            )
            result = resp.json()
            if result.get("code") != 200:
                raise RuntimeError(f"Echec upload: {result.get('message', '')}")
            return result["data"]

    def create_folder(self, parent_node_info, folder_name):
        payload = {
            "parentNode": parent_node_info,
            "libelle": folder_name,
            "typeRessource": "folder",
        }
        return self._post_json("ajouter", payload)

    def delete_to_trash(self, tab_nodes):
        return self._post_json("delete", {"tabNodes": tab_nodes})

    def delete_permanently(self, tab_nodes):
        return self._post_json("delete", {"tabNodes": tab_nodes},
                               extra_params={"permanent": "1"})

    def copy(self, dest_parent_node, clipboard_nodes):
        payload = {
            "parentNode": dest_parent_node,
            "clipboard": clipboard_nodes,
        }
        return self._post_json("copier", payload)

    def rename(self, node_info, new_name):
        return self._post_json("renommer", {
            "node": node_info,
            "newLibelle": new_name,
        })
