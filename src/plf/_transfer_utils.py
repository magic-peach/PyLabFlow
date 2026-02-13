import json
from pathlib import Path
from typing import List, Set
from .context import get_shared_data
    
    
    


def _load_transfer_config():
    settings = get_shared_data()

    lab_base = Path(settings["data_path"]).resolve()

    transfers_dir = lab_base / "Transfers"
    transfers_dir.mkdir(exist_ok=True)

    cfg_path = transfers_dir / "transfer_config.json"
    if not cfg_path.exists():
        return {
            "active_transfer_id": None,
            "history": [],
            "ppl_to_transfer": {} #sqlit3
        }
    return json.loads(cfg_path.read_text(encoding="utf-8"))
# ---------------------------


# ---------------------------
# TransferContext
# ---------------------------
class TransferContext:
    """Runtime context for remapping paths and components on remote."""

    def __init__(self):
        settings = get_shared_data()

        transfers_dir = Path(settings["data_path"]).resolve() / "Transfers"
        self.transfers_dir = transfers_dir
        self._cfg = _load_transfer_config()
        self.__db = None

    def _get_db(self):
        if self.__db is None:
            from .utils import Db
            settings = get_shared_data()
            self.__db = Db(db_path=f"{settings['data_path']}/ppls.db")
        return self.__db

    def get_dependencies(self, pplid: str, recursive: bool = True) -> List[str]:
        """
        Get all dependencies for a given pplid.

        Queries the edges table to find pipelines that the given pplid depends on.
        Can recursively get all dependencies.

        Args:
            pplid: The pipeline ID to get dependencies for
            recursive: If True, recursively get all dependencies

        Returns:
            List of pipeline IDs that this pplid depends on
        """
        db = self._get_db()
        dependencies = set()

        def collect_deps(pplid: str):
            rows = db.query(
                "SELECT prev FROM edges WHERE next = ? LIMIT 1",
                (pplid,)
            )
            if rows and rows[0][0]:
                prev_pplid = rows[0][0]
                if prev_pplid not in dependencies:
                    dependencies.add(prev_pplid)
                    if recursive:
                        collect_deps(prev_pplid)

        collect_deps(pplid)
        return list(dependencies)

    def _load_transfer_meta(self, transfer_id: str) -> dict:
        meta_path = self.transfers_dir / transfer_id / "transfer.json"
        if not meta_path.exists():
            return {}
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def map_cnfg(self, cnfg): 

        pplid = cnfg['pplid']       
        def remap(d):
            if isinstance(d, dict):
                for k, v in d.items():
                    if "loc" in k and isinstance(v, str):
                        # Map LOC via transfer context
                        d[k] = self.map_loc(v, pplid=pplid)
                    elif 'src' in k and isinstance(v, str):
                        # Map file paths via transfer context
                        d[k] = self.map_src(v)
                    else:
                        remap(v)
            elif isinstance(d, list):
                for item in d:
                    remap(item)
        remap(cnfg)
        return cnfg

    def map_src(self, src: str, pplid: str) -> str:
        src = Path(src).as_posix()
        transfer_id = self._cfg["ppl_to_transfer"].get(pplid)
        if not transfer_id:
            return src

        meta = self._load_transfer_meta(transfer_id)
        path_map = meta.get("path_map", {})

        for src, dst in path_map.items():
            dst = self.transfers_dir / transfer_id /"payload"/ dst
            if src.startswith(src):
                return src.replace(src, dst, 1)

        return src

    def map_loc(self, loc: str, pplid: str) -> str:
        transfer_id = self._cfg["ppl_to_transfer"].get(pplid)
        if not transfer_id:
            return loc

        meta = self._load_transfer_meta(transfer_id)
        loc_map = meta.get("loc_map", {})

        return loc_map.get(loc, loc)

    def resolve_dependencies(self, pplids: List[str]) -> List[str]:
        """
        Resolve all dependencies for a given list of pipeline IDs.

        Takes a list of pplids and returns a new list that includes
        all of those pplids plus any dependencies they have, recursively.

        Args:
            pplids: List of pipeline IDs to transfer

        Returns:
            Complete list of pipeline IDs including all dependencies
        """
        all_pplids = set(pplids)
        resolved = set(pplids)

        for pplid in pplids:
            deps = self.get_dependencies(pplid, recursive=True)
            all_pplids.update(deps)
            resolved.update(deps)

        return list(all_pplids)
