# app/schemas.py
from pydantic import BaseModel

class NoteIn(BaseModel):
    title: str
    content: str

class NoteOut(NoteIn):
    id: int