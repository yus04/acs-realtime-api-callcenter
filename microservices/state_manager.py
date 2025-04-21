from models import ConversationState
from typing import Dict, Optional
from interface import WebSocketInterface
from realtime import Realtime

class ConversationStateManager:
    def __init__(self):
        self._states: Dict[str, ConversationState] = {}
    
    def create(self, call_id: str) -> ConversationState:
        state = ConversationState(call_id = call_id)
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


class RealtimeManager:
    def __init__(self) -> None:
        self._clients: Dict[str, Realtime] = {}

    def create(self, call_id: str, web_socket: WebSocketInterface) -> Realtime:
        # 既存クライアントがあれば停止・削除
        if call_id in self._clients:
            self.delete(call_id)

        client = Realtime(web_socket)
        self._clients[call_id] = client
        return client

    def get(self, call_id: str) -> Optional[Realtime]:
        return self._clients.get(call_id)

    def exists(self, call_id: str) -> bool:
        return call_id in self._clients

    def delete(self, call_id: str) -> None:
        client = self._clients.pop(call_id, None)
        if client:
            # クライアントの後始末（WebSocket や RT client を閉じる）
            try:
                import asyncio
                asyncio.create_task(client.rtclient_close())
            except Exception:
                pass
