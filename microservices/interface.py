from typing import Protocol

class RealtimeInterface(Protocol):
    async def send_audio_buffer_to_realtime_api(self, audio_data: str) -> None:
        ...
    async def start_realtime_conversation_loop(self, call_id: str) -> None:
        ...
    async def rtclient_close(self) -> None:
        ...

class WebSocketInterface(Protocol):
    async def send_text_to_acs(self, audio_data_base64: str) -> None:
        ...

