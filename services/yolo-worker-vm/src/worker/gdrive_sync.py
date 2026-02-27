"""Daily Google Drive sync for processed images.

Uploads ocorrencias/ and sem_ocorrencia/ under each device directory to the
configured Google Drive folder, then deletes sem_ocorrencia/ locally to free
disk space.  ocorrencias/ and labeled/ are kept on disk.

Authentication uses a Google service account JSON key file mounted into the
container.  Set GDRIVE_SA_KEY_PATH to the path of the key file, and
GDRIVE_FOLDER_ID to the ID of the destination Drive folder.

Drive folder structure mirrors the local layout:
    <GDRIVE_FOLDER_ID>/
        <device_id>/
            ocorrencias/
                <YYYY>/<MM>/<DD>/<filename>.jpg
            sem_ocorrencia/
                <YYYY>/<MM>/<DD>/<filename>.jpg
"""
import logging
import mimetypes
import os
import shutil
from pathlib import Path

from . import config

logger = logging.getLogger("worker.gdrive")


def _get_drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    credentials = service_account.Credentials.from_service_account_file(
        config.GDRIVE_SA_KEY_PATH,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    """Return the Drive folder ID for *name* under *parent_id*, creating it if absent."""
    q = (
        f"name='{name}' "
        f"and mimeType='application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents "
        f"and trashed=false"
    )
    result = service.files().list(q=q, fields="files(id)", pageSize=1).execute()
    files = result.get("files", [])
    if files:
        return files[0]["id"]
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def _file_exists_on_drive(service, name: str, parent_id: str) -> bool:
    q = f"name='{name}' and '{parent_id}' in parents and trashed=false"
    result = service.files().list(q=q, fields="files(id)", pageSize=1).execute()
    return bool(result.get("files"))


def _upload_file(service, local_path: Path, parent_folder_id: str) -> None:
    """Upload *local_path* to Drive under *parent_folder_id*; skip if already present."""
    from googleapiclient.http import MediaFileUpload

    if _file_exists_on_drive(service, local_path.name, parent_folder_id):
        return

    mime_type = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=False)
    metadata = {"name": local_path.name, "parents": [parent_folder_id]}
    service.files().create(body=metadata, media_body=media, fields="id").execute()


def _upload_directory_tree(service, local_dir: Path, drive_root_id: str) -> int:
    """Recursively upload all .jpg files under *local_dir* to Drive. Returns file count."""
    # Cache: tuple of path parts relative to local_dir → Drive folder ID
    folder_id_cache: dict[tuple, str] = {(): drive_root_id}
    count = 0

    for file_path in sorted(local_dir.rglob("*.jpg")):
        rel = file_path.relative_to(local_dir)
        parts = rel.parts  # e.g. ("2026", "01", "15", "filename.jpg")

        # Resolve / create all intermediate folders
        current_parent_id = drive_root_id
        for i, part in enumerate(parts[:-1]):  # skip the filename
            key = parts[: i + 1]
            if key not in folder_id_cache:
                folder_id_cache[key] = _get_or_create_folder(service, part, current_parent_id)
            current_parent_id = folder_id_cache[key]

        try:
            _upload_file(service, file_path, current_parent_id)
            count += 1
        except Exception:
            logger.exception("Failed to upload %s", file_path)

    return count


def sync_uploads_to_drive() -> None:
    """Main entry point: upload processed images to Drive, then prune sem_ocorrencia/ locally."""
    if not config.GDRIVE_FOLDER_ID:
        logger.warning("GDRIVE_FOLDER_ID not set — skipping Drive sync.")
        return
    if not os.path.exists(config.GDRIVE_SA_KEY_PATH):
        logger.warning(
            "Service account key not found at %s — skipping Drive sync.",
            config.GDRIVE_SA_KEY_PATH,
        )
        return

    service = _get_drive_service()
    upload_dir = Path(config.UPLOAD_DIR)

    for device_dir in sorted(upload_dir.iterdir()):
        if not device_dir.is_dir():
            continue
        device_id = device_dir.name

        device_drive_id = _get_or_create_folder(service, device_id, config.GDRIVE_FOLDER_ID)

        for subfolder_name in ("ocorrencias", "sem_ocorrencia"):
            local_sub = device_dir / subfolder_name
            if not local_sub.exists():
                continue

            sub_drive_id = _get_or_create_folder(service, subfolder_name, device_drive_id)
            n = _upload_directory_tree(service, local_sub, sub_drive_id)
            logger.info(
                "Drive sync: uploaded %d file(s) from %s/%s",
                n, device_id, subfolder_name,
            )

        # Delete sem_ocorrencia/ locally after successful upload to free disk space.
        sem_local = device_dir / "sem_ocorrencia"
        if sem_local.exists():
            shutil.rmtree(sem_local)
            logger.info("Deleted local sem_ocorrencia/ for device %s", device_id)
