import asyncio
import json
from datetime import datetime
from fastapi import WebSocket as FastAPIWebSocket
from models import ConversationState
from interface import RealtimeInterface, WebSocketInterface

class WebSocket(WebSocketInterface):
    def __init__(self, websocket: FastAPIWebSocket, call_id: str, realtime: RealtimeInterface) -> None:
        self._websocket = websocket
        self._call_id = call_id
        self._realtime = realtime

    async def websocket_handler(self, conversation_state: ConversationState) -> None:
        await self._websocket.accept()
        print(f"WebSocket connection established for call_id: {conversation_state.call_id}")
        await self._realtime.start_realtime_conversation_loop(conversation_state)
        await self.start_acs_conversation_loop()
    
    async def websocket_update(self, conversation_state: ConversationState) -> None:
        print(f"WebSocket update for call_id: {conversation_state.call_id}")
        await self._realtime.start_realtime_conversation_loop(conversation_state)

    async def start_acs_conversation_loop(self) -> None:   
        asyncio.create_task(self.transfer_acs_to_realtime_api_until_disconnect())

    async def transfer_acs_to_realtime_api_until_disconnect(self) -> None:
        try:
            while True:
                message = await self._websocket.receive()
                msg_type = message.get('type')

                if msg_type == 'websocket.receive':
                    payload = json.loads(message['text'])
                    kind = payload.get('kind')

                    if kind != 'AudioData':
                        print(f"Skipping non-audio payload kind: {kind}")
                        continue

                    audio_data_base64 = payload.get('audioData', {}).get('data')
                    if not audio_data_base64:
                        print(f"Unexpected payload format or no audio data: {payload}")
                        continue
                    
                    await self._realtime.send_audio_buffer_to_realtime_api(audio_data_base64)
                
                elif msg_type == 'websocket.disconnect':
                    print("WebSocket disconnected")
                    break

        except Exception as e:
            print(f"Exception in receive_message_until_disconnect: {e}")
        
        finally:
            try:
                await self._realtime.rtclient_close()
            except Exception as e:
                print(f"Error closing realtime client: {e}")
            print(f"Connection closed for call_id: {self._call_id}")

    async def send_text_to_acs(self, audio_data_base64: str) -> None:
        message = {
            "kind": "AudioData",
            "audioData": {
                "timestamp": datetime.utcnow().isoformat() + 'Z',
                "data": audio_data_base64,
                "silent": False
            }
        }
        message_str = json.dumps(message)
        await self._websocket.send_text(message_str)
