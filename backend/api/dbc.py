"""Saved DBC files, active selection and persistent favorites."""
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.dbc_workspace import workspace

router = APIRouter()
MAX_DBC_SIZE = 20 * 1024 * 1024


class ActiveRequest(BaseModel):
    dbc_ids: list[str]


class FavoriteRequest(BaseModel):
    dbc_id: str
    message_name: str
    signal_name: str | None = None
    favorite: bool


class ProgramRequest(BaseModel):
    name: str


class SelectProgramRequest(BaseModel):
    program_id: str


@router.post('/programs')
def create_program(req: ProgramRequest):
    return _call(lambda: workspace.create_program(req.name))


@router.post('/programs/select')
def select_program(req: SelectProgramRequest):
    return _call(lambda: workspace.select_program(req.program_id))


def _call(action):
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _read_upload(file):
    if not file.filename or not file.filename.lower().endswith('.dbc'):
        raise HTTPException(status_code=400, detail='Only .dbc files are supported')
    content = await file.read(MAX_DBC_SIZE + 1)
    if len(content) > MAX_DBC_SIZE:
        raise HTTPException(status_code=413, detail='DBC files must be at most 20 MiB each')
    return file.filename, content


@router.get('/state')
def state():
    return workspace.state()


@router.post('/upload')
async def upload_dbc(file: UploadFile = File(...)):
    entry = await _read_upload(file)
    return _call(lambda: workspace.upload([entry]))


@router.post('/upload-many')
async def upload_dbcs(files: list[UploadFile] = File(...)):
    if len(files) > 20:
        raise HTTPException(status_code=400, detail='Add at most 20 DBC files per upload')
    entries = [await _read_upload(file) for file in files]
    return _call(lambda: workspace.upload(entries))


@router.post('/active')
def active(req: ActiveRequest):
    return _call(lambda: workspace.activate(req.dbc_ids))


@router.delete('/files/{dbc_id}')
def delete_dbc(dbc_id: str):
    return _call(lambda: workspace.delete(dbc_id))


@router.post('/favorites')
def favorite(req: FavoriteRequest):
    return _call(lambda: workspace.favorite(req.dbc_id, req.message_name, req.signal_name, req.favorite))


@router.get('/messages')
def get_messages():
    return workspace.sender.get_all_messages()


@router.get('/messages/{message_name}/signals')
def get_signals(message_name: str, dbc_id: str | None = None):
    matches = [m for m in workspace.sender.get_all_messages()['messages']
               if m['name'] == message_name and (not dbc_id or m['dbc_id'] == dbc_id)]
    if len(matches) != 1:
        raise HTTPException(status_code=400, detail='Specify an active DBC and an unambiguous message name')
    return {'message': matches[0]}


@router.delete('/unload')
def unload_dbc():
    # Disabling files keeps their bytes and favorites for later reuse.
    return _call(lambda: workspace.activate([]))
