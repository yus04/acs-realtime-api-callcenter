from pydantic import BaseModel
from typing import Optional

class ConversationState(BaseModel):
    call_id: str
    caller_id: Optional[str] = None
    current_role: Optional[str] = None
    job_id: Optional[str] = None
    job_assignment_id: Optional[str] = None
    queue_id: Optional[str] = None
    worker_id: Optional[str] = None
    conversation_summary: Optional[str] = None
