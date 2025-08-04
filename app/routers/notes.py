# app/routers/notes.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db import get_session
from app.models import Note
from app.schemas import NoteIn, NoteOut

router = APIRouter(prefix="/notes", tags=["notes"])

@router.get("", response_model=list[NoteOut])
def list_notes(s: Session = Depends(get_session)):
    rows = s.query(Note).order_by(Note.id.desc()).all()
    return [NoteOut(id=r.id, title=r.title, content=r.content) for r in rows]

@router.post("", response_model=NoteOut, status_code=201)
def create_note(note: NoteIn, s: Session = Depends(get_session)):
    row = Note(title=note.title, content=note.content)
    s.add(row); s.commit(); s.refresh(row)
    return NoteOut(id=row.id, title=row.title, content=row.content)

@router.delete("/{note_id}", status_code=204)
def delete_note(note_id: int, s: Session = Depends(get_session)):
    row = s.get(Note, note_id)
    if not row:
        raise HTTPException(404, "not_found")
    s.delete(row); s.commit()
    return