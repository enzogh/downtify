"""Jam API: listen together to one shared queue (see :mod:`downtify.jam`).

* ``GET /api/jam`` - ``{jam}``: the Jam you are in, or ``null``.
* ``POST /api/jam`` - start a Jam you host (leaving any other).
* ``POST /api/jam/join`` ``{code}`` - join with a code (or a join link).
* ``POST /api/jam/leave`` - leave it; the host leaving ends it.
* ``PATCH /api/jam`` ``{guests_can_control}`` - host only.
* ``POST /api/jam/queue`` ``{tracks, position, play}`` - add library
  songs (``position``: ``'end'``, ``'next'`` or an index).
* ``DELETE /api/jam/queue/{item_id}`` - remove a song.
* ``POST /api/jam/queue/move`` ``{item_id, to}`` - reorder.
* ``POST /api/jam/queue/clear`` - drop the songs after the current one.
* ``POST /api/jam/control`` ``{action, position?, index?, from_index?}``
  - ``play``, ``pause``, ``seek``, ``next``, ``prev``, ``jump`` and
  ``ended`` (a device reached the end of song ``from_index``).

Every change is sent to each member's sockets as
``{type: 'jam', jam: {...}}``; a member who left (or whose Jam ended)
gets ``{type: 'jam', jam: null}``. Every answer carries the same
``{jam}`` snapshot, whose ``position`` was read at ``now`` (server clock,
seconds) so a client can tell where the song is when it arrives.
"""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import api
from .jam import MAX_QUEUE, JamError, JamStore
from .library_catalog import resolve_library_file

router = APIRouter(prefix='/api/jam')

store = JamStore()


class JoinBody(BaseModel):
    code: str = Field(min_length=1, max_length=500)


class SettingsBody(BaseModel):
    guests_can_control: bool


class TrackBody(BaseModel):
    file: str = Field(min_length=1, max_length=2000)
    title: str = Field(default='', max_length=2000)
    artist: str = Field(default='', max_length=2000)
    album: str = Field(default='', max_length=2000)
    duration: float = 0


class AddBody(BaseModel):
    tracks: list[TrackBody] = Field(min_length=1, max_length=MAX_QUEUE)
    position: Union[Literal['end', 'next'], int] = 'end'
    play: bool = False


class MoveBody(BaseModel):
    item_id: str = Field(min_length=1, max_length=64)
    to: int = Field(ge=0)


class ControlBody(BaseModel):
    action: str = Field(min_length=1, max_length=16)
    position: Optional[float] = Field(default=None, ge=0)
    index: Optional[int] = Field(default=None, ge=0)
    from_index: Optional[int] = None


def _who(request: Request) -> tuple[int, str]:
    principal = api.principal_of(request)
    user_id = int(getattr(principal, 'user_id', 0) or 0)
    if not user_id:
        raise HTTPException(status_code=401, detail='Sign in to use Jams')
    return user_id, str(getattr(principal, 'username', '') or '')


async def _send(
    snapshot: Optional[dict[str, Any]], members: list[int]
) -> None:
    for uid in members:
        await api.state.connections.send_user(
            uid, {'type': 'jam', 'jam': snapshot}
        )


async def _announce(snapshot: dict[str, Any], gone: list[int] = ()) -> dict:
    await _send(snapshot, [m['id'] for m in snapshot['members']])
    await _send(None, list(gone))
    return {'jam': snapshot}


def _refused(err: JamError) -> HTTPException:
    return HTTPException(status_code=err.status, detail=err.message)


@router.get('')
def get_jam(request: Request) -> dict[str, Any]:
    user_id, _ = _who(request)
    return {'jam': store.get(user_id)}


@router.post('')
async def start_jam(request: Request) -> dict[str, Any]:
    user_id, name = _who(request)
    try:
        snapshot, gone = store.start(user_id, name)
    except JamError as err:
        raise _refused(err) from err
    return await _announce(snapshot, gone)


@router.post('/join')
async def join_jam(request: Request, body: JoinBody) -> dict[str, Any]:
    user_id, name = _who(request)
    try:
        snapshot, gone = store.join(user_id, name, body.code)
    except JamError as err:
        raise _refused(err) from err
    return await _announce(snapshot, gone)


@router.post('/leave')
async def leave_jam(request: Request) -> dict[str, Any]:
    user_id, _ = _who(request)
    gone, remaining = store.leave(user_id)
    await _send(None, gone)
    if remaining:
        snapshot = store.get(remaining[0])
        if snapshot is not None:
            await _send(snapshot, remaining)
    return {'jam': None}


@router.patch('')
async def configure_jam(
    request: Request, body: SettingsBody
) -> dict[str, Any]:
    user_id, _ = _who(request)
    try:
        snapshot = store.configure(user_id, body.guests_can_control)
    except JamError as err:
        raise _refused(err) from err
    return await _announce(snapshot)


@router.post('/queue')
async def add_to_jam(request: Request, body: AddBody) -> dict[str, Any]:
    user_id, _ = _who(request)
    ctx = api.library_context()
    tracks = [
        track.model_dump()
        for track in body.tracks
        if resolve_library_file(track.file, ctx) is not None
    ]
    if not tracks:
        raise HTTPException(
            status_code=400, detail='Only library songs can join a Jam'
        )
    try:
        snapshot = store.add(user_id, tracks, body.position, body.play)
    except JamError as err:
        raise _refused(err) from err
    return await _announce(snapshot)


@router.delete('/queue/{item_id}')
async def remove_from_jam(request: Request, item_id: str) -> dict[str, Any]:
    user_id, _ = _who(request)
    try:
        snapshot = store.remove(user_id, item_id)
    except JamError as err:
        raise _refused(err) from err
    return await _announce(snapshot)


@router.post('/queue/move')
async def move_in_jam(request: Request, body: MoveBody) -> dict[str, Any]:
    user_id, _ = _who(request)
    try:
        snapshot = store.move(user_id, body.item_id, body.to)
    except JamError as err:
        raise _refused(err) from err
    return await _announce(snapshot)


@router.post('/queue/clear')
async def clear_jam(request: Request) -> dict[str, Any]:
    user_id, _ = _who(request)
    try:
        snapshot = store.clear_upcoming(user_id)
    except JamError as err:
        raise _refused(err) from err
    return await _announce(snapshot)


@router.post('/control')
async def control_jam(request: Request, body: ControlBody) -> dict[str, Any]:
    user_id, _ = _who(request)
    try:
        snapshot = store.control(
            user_id,
            body.action,
            position=body.position,
            index=body.index,
            from_index=body.from_index,
        )
    except JamError as err:
        raise _refused(err) from err
    if snapshot is None:
        # Another device already reported this song's end.
        return {'jam': store.get(user_id)}
    return await _announce(snapshot)
