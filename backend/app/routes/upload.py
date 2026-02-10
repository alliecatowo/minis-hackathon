import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.core.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/upload", tags=["upload"])

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB


@router.post("/claude-code")
async def upload_claude_code(
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
):
    """Upload Claude Code JSONL files for enhanced mini creation."""
    upload_dir = Path(f"data/uploads/{user.id}/claude_code")
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved_count = 0
    total_size = 0

    for file in files:
        if not file.filename:
            continue

        content = await file.read()
        if len(content) > MAX_UPLOAD_SIZE:
            raise HTTPException(413, f"File {file.filename} exceeds 50MB limit")

        total_size += len(content)

        if file.filename.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for name in zf.namelist():
                    if name.endswith(".jsonl"):
                        dest = upload_dir / Path(name).name
                        if not dest.resolve().is_relative_to(upload_dir.resolve()):
                            continue  # skip malicious paths
                        dest.write_bytes(zf.read(name))
                        saved_count += 1
        elif file.filename.endswith(".jsonl"):
            dest = upload_dir / Path(file.filename).name
            if not dest.resolve().is_relative_to(upload_dir.resolve()):
                continue  # skip malicious paths
            dest.write_bytes(content)
            saved_count += 1
        else:
            continue

    if saved_count == 0:
        raise HTTPException(400, "No .jsonl files found in upload")

    return {"files_saved": saved_count, "total_size": total_size}
