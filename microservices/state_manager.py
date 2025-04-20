from models import ConversationState
from typing import Dict, Optional

class ConversationStateManager:
    def __init__(self):
        self._states: Dict[str, ConversationState] = {}
    
    def create(self, call_id: str) -> ConversationState:
        state = ConversationState(call_id)
        self._states[call_id] = state
        return self._states[call_id]

    def get(self, call_id: str) -> Optional[ConversationState]:
        return self._states.get(call_id)

    def update(self, call_id: str, **kwargs) -> None:
        state = self._states.get(call_id)
        if state:
            for key, value in kwargs.items():
                if hasattr(state, key):
                    setattr(state, key, value)

    def delete(self, call_id: str) -> None:
        if call_id in self._states:
            del self._states[call_id]

    def exists(self, call_id: str) -> bool:
        return call_id in self._states
