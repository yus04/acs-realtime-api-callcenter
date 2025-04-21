import asyncio
from settings import settings
from models import ConversationState
from realtime_instruct import get_instructions
from azure.core.credentials import AzureKeyCredential
from interface import RealtimeInterface, WebSocketInterface
from rtclient import (
    ResponseCreateMessage,
    RTLowLevelClient,
    ResponseCreateParams,
    InputAudioBufferAppendMessage
)

class Realtime(RealtimeInterface):
    def __init__(self, webSocket: WebSocketInterface) -> None:
        self._aoai_service_endpoint = settings.AZURE_OPENAI_SERVICE_ENDPOINT
        self._aoai_deployment_name = settings.AZURE_OPENAI_DEPLOYMENT_NAME
        self._aoai_service_key = settings.AZURE_OPENAI_SERVICE_KEY
        self._rtclient = self._init_rtclient()
        self._transcript_buffer = ""
        self._send_text_to_acs = webSocket.send_text_to_acs
        self._transfer_task: asyncio.Task | None = None

    def _init_rtclient(self) -> RTLowLevelClient:
        rtclient = RTLowLevelClient(
            url = self._aoai_service_endpoint,
            azure_deployment = self._aoai_deployment_name,
            key_credential = AzureKeyCredential(self._aoai_service_key),
        )
        return rtclient
    
    async def start_realtime_conversation_loop(self, conversation_state: ConversationState) -> None:
        # 既存タスクがあればキャンセル＆クライアントをクローズ
        if self._transfer_task:
            self._transfer_task.cancel()
            try:
                await self._transfer_task
            except asyncio.CancelledError:
                pass
            # クライアント側もクローズしてから再初期化
            await self._rtclient.close()
            self._rtclient = self._init_rtclient()
        current_role = conversation_state.current_role
        instructions = get_instructions(current_role)
        await self._rtclient.connect()
        await self._send_instructions(instructions)
        # 新しい転送タスクを作成
        self._transfer_task = asyncio.create_task(
            self.transfer_realtime_api_to_acs_until_disconnect(conversation_state.call_id)
        )
    
    async def transfer_realtime_api_to_acs_until_disconnect(self, call_id: str) -> None:
        try:
            while True:
                message = await self._rtclient.recv()
                if message is None:
                   print(f"No message received, closing loop for call_id: {call_id}")
                   break

                if message.type == "response.audio.delta":
                    audio_data_base64 = message.delta
                    await self._send_text_to_acs(audio_data_base64)
                elif message.type == "response.audio_transcript.delta":
                    transcript_delta = message.delta
                    self._output_complete_message(transcript_delta)
                elif message.type == "input.audio_transcript":
                    user_transcript = message.text
                    print(f"User transcript: {user_transcript}")
                else:
                    print(f"Unknown message type: {message.type}")
        except Exception as e:
            print(f"Exception in transfer_realtime_api_to_acs_until_disconnect: {e}")
        finally:
            await self._rtclient.close()
            print(f"Connection closed for call_id: {call_id}")

    def _output_complete_message(self, transcript_delta: str) -> ResponseCreateMessage:
        self._transcript_buffer += transcript_delta
        if any(transcript_delta.endswith(punct) for punct in ['。', '！', '？', '.', '!', '?', '」', '\n']):
            complete_sentence = self._transcript_buffer.strip()
            print(f"Complete sentence: {complete_sentence}")
            self._transcript_buffer = ""

    async def send_audio_buffer_to_realtime_api(self, audio_data: str) -> None:
        message = self._audio_buffer_append_message(audio_data)
        await self._rtclient.send(message)

    def _audio_buffer_append_message(self, audio_data: str) -> InputAudioBufferAppendMessage:
        message = InputAudioBufferAppendMessage(
            type = "input_audio_buffer.append",
            audio = audio_data
        )
        return message
    
    async def _send_instructions(self, instructions: str) -> None:
        message = self._response_create_message(instructions)
        await self._rtclient.send(message)
    
    def _response_create_message(self, instructions: str) -> ResponseCreateMessage:
        params = ResponseCreateParams(
            modalities = {"audio", "text"},
            instructions = instructions,
            voice = "shimmer",
            output_audio_format = "pcm16",
            input_audio_format = "pcm16",
            input_audio_transcription = {"model": "whisper-1"}
        )
        message = ResponseCreateMessage(
            response = params
        )
        return message
    
    async def rtclient_close(self) -> None:
        try:
            await self._rtclient.close()
        except AttributeError:
            # ws が存在しない場合は何もしない
            pass
