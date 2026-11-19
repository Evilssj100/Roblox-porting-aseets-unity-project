# Paste this whole file into the Blender MCP (execute_blender_code) once per Blender session. It defines two
# helpers in bpy.app.driver_namespace that only DOWNLOAD files from GitHub and UPLOAD them to Roblox with the
# Roblox Uploader add-on's own credentials (the key is never read out or printed). They never touch the
# user's scenes, never export and never save.
#   spso_upload_package(commit)   PATCH the code package (studio/SPSO_Package.rbxmx) -> asset 113546958541177
#   spso_upload_jobs(commit)      POST every job in studio/upload/jobs.json, 3 at a time, in a background
#                                 thread; poll bpy.app.driver_namespace["spso_bulk"] for done/total/results/errors
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import bpy

REPO = "https://raw.githubusercontent.com/Evilssj100/Roblox-porting-aseets-unity-project/"


def spso_upload_package(commit, asset_id="113546958541177"):
    m = sys.modules["roblox_uploader"]
    p = m._prefs()
    path = os.path.join(tempfile.gettempdir(), "spso_rbx", "package", "SPSO_Package.rbxmx")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    urllib.request.urlretrieve(f"{REPO}{commit}/roblox-port/studio/SPSO_Package.rbxmx", path)
    job = {"method": "PATCH", "url": f"{m.API}/assets/{asset_id}", "path": path, "ctype": "model/x-rbxm", "asset_id": asset_id,
           "request": {"assetType": "Model", "assetId": asset_id, "creationContext": {"creator": m._creator(p)}}}
    aid, mod = m._run_one(job, m._key(p))
    return {"assetId": aid, "moderation": mod, "bytes": os.path.getsize(path)}


def spso_upload_jobs(commit, jobs_rel="roblox-port/studio/upload/jobs.json", workers=3):
    m = sys.modules["roblox_uploader"]
    p = m._prefs()
    key, creator = m._key(p), m._creator(p)
    base = f"{REPO}{commit}/"
    root = os.path.join(tempfile.gettempdir(), "spso_rbx", "bulk", commit)
    os.makedirs(root, exist_ok=True)
    jobs = json.loads(urllib.request.urlopen(base + jobs_rel).read())
    state = {"commit": commit, "total": len(jobs), "done": 0, "results": {}, "errors": {}, "running": True, "started": time.time()}
    bpy.app.driver_namespace["spso_bulk"] = state

    def one(j):
        path = os.path.join(root, os.path.basename(j["path"]))
        try:
            for attempt in range(5):
                try:
                    if not os.path.exists(path):
                        urllib.request.urlretrieve(base + j["path"], path)
                    at = {"image": "Image", "audio": "Audio"}.get(j["kind"], "Model")
                    req = {"assetType": at, "displayName": j["name"], "description": "SPSO port asset",
                           "creationContext": {"creator": creator}}
                    job = {"method": "POST", "url": f"{m.API}/assets", "path": path, "ctype": j["ctype"], "request": req, "asset_id": ""}
                    aid, _ = m._run_one(job, key)
                    state["results"][j["key"]] = str(aid)
                    state["errors"].pop(j["key"], None)
                    return
                except Exception as e:  # noqa: BLE001 - keep going, report per job
                    msg = str(e)[:300]
                    state["errors"][j["key"]] = msg
                    busy = any(s in msg for s in ("429", "Too Many", "imed out", "503", "502"))
                    time.sleep((6 if busy else 2) * (attempt + 1))
        finally:
            state["done"] += 1

    def run():
        try:
            with ThreadPoolExecutor(workers) as ex:
                list(ex.map(one, jobs))
        finally:
            state["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return {"queued": len(jobs)}


bpy.app.driver_namespace["spso_upload_package"] = spso_upload_package
bpy.app.driver_namespace["spso_upload_jobs"] = spso_upload_jobs
result = {"helpers": ["spso_upload_package", "spso_upload_jobs"]}
