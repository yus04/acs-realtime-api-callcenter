from settings import settings
from urllib.parse import urlencode, urlparse
from call_context import CallContext
from azure.communication.callautomation.aio import CallAutomationClient
from azure.communication.callautomation import (
    CallConnectionClient,
    MediaStreamingOptions,
    AudioFormat,
    MediaStreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    PhoneNumberIdentifier
)

class CallHandler:
    def __init__(self) -> None:
        connection_string = settings.ACS_CONNECTION_STRING
        self._callback_baseurl = settings.CALLBACK_BASEURL
        self._operator_phone_number = settings.OPERATOR_PHONE_NUMBER
        self._automation_client: CallAutomationClient = (
            CallAutomationClient.from_connection_string(connection_string)
        )
        self._connection_client: CallConnectionClient = (
            CallConnectionClient.from_connection_string(connection_string)
        )

    async def answer_call(self, incoming_call_context: str, call_context: CallContext) -> None:
        await self._automation_client.answer_call(
            incoming_call_context = incoming_call_context,
            operation_context = "incomingCall",
            callback_url = self._callback_url(call_context),
            media_streaming = self._media_streaming_options(call_context),
        )
    
    def _media_streaming_options(self, call_context: CallContext) -> MediaStreamingOptions:
        options = MediaStreamingOptions(
            transport_url = self._websocket_url(call_context),
            transport_type = MediaStreamingTransportType.WEBSOCKET,
            content_type = MediaStreamingContentType.AUDIO,
            audio_channel_type = MediaStreamingAudioChannelType.MIXED,
            start_media_streaming = True,
            enable_bidirectional = True,
            audio_format = AudioFormat.PCM24_K_MONO,
        )
        return options

    def _callback_url(self, call_context: CallContext) -> str:
        call_id = call_context.call_id
        caller_id = call_context.conversation_state.caller_id
        query_parameters = urlencode({"callerId": caller_id})
        callback_url = f"{self._callback_baseurl}/{call_id}?{query_parameters}"
        return callback_url

    def _websocket_url(self, call_context: CallContext) -> str:
        call_id = call_context.call_id
        parsed_url = urlparse(self._callback_baseurl)
        websocket_url = f"wss://{parsed_url.netloc}/ws/{call_id}"
        return websocket_url

    def get_call_connection(self, call_id: str) -> CallConnectionClient:
        return self._automation_client.get_call_connection(
            call_id = call_id
        )

    def transfer_call(self, call_context: CallContext) -> None:
        self._connection_client.transfer_call_to_participant(
            target_participant = self._phone_number_identifier(),
            operation_context = call_context.conversation_state.conversation_summary,
            operation_callback_url = "<url_endpoint>"
        )
    
    async def hangup(self, call_context: CallContext) -> None:
        try:
            await self._connection_client.hang_up(is_for_everyone = True)
        except Exception as e:
            print(f"Error during hangup for connection {call_context.conversation_state.call_id}: {e}")

    def _phone_number_identifier(self) -> PhoneNumberIdentifier:
        return PhoneNumberIdentifier(
            phone_number = self._operator_phone_number
        )
