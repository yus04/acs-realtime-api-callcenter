import uuid
from typing import Optional
from fastapi import Request
from models import ConversationState
from state_manager import ConversationStateManager
from azure.core.messaging import CloudEvent

class CallContext:
    def __init__(self, call_id, events, conversation_state):
        self.call_id: str = call_id
        self.events: CloudEvent = events
        self.conversation_state: ConversationState = conversation_state

class CallContextFactory:
    def __init__(self, request: Request, call_id: Optional[str] = None):
        self.request = request
        self.call_id = call_id

    async def build(self) -> CallContext:
        events = await self.request.json()
        conversation_state_manager: ConversationStateManager = (
            self.request.app.state.conversation_state_manager
        )
        
        # Callback 時
        if self.call_id:
            conversation_state = conversation_state_manager.get(self.call_id)
        # Incoming call 時
        else:
            conversation_state = conversation_state_manager.create(str(uuid.uuid4()))
            self.call_id = conversation_state.call_id

        return CallContext(
            call_id = self.call_id,
            events = events,
            conversation_state = conversation_state
        )
