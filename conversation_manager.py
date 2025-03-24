import asyncio
import json
import base64
from datetime import datetime
from azure.core.credentials import AzureKeyCredential
from rtclient import (
    ResponseCreateMessage,
    RTLowLevelClient,
    ResponseCreateParams,
    InputAudioBufferAppendMessage
)
from config import AZURE_OPENAI_SERVICE_ENDPOINT, AZURE_OPENAI_SERVICE_KEY, AZURE_OPENAI_DEPLOYMENT_NAME
from utils import print_debug

def get_instructions(current_role: str) -> str:
    """
    共通化した指示文の生成関数。
    """
    if current_role == 'RoleA':
        return """
            あなたは日本語の AI アシスタントです。
            ユーザーからの質問にわかりやすく丁寧に回答してください。
            また、最初は「お電話変わりました。AI アシスタントです。ご要件をお伺いいたします。」
            と言ってください。
        """
    elif current_role == 'RoleB':
        return """
            You are English AI assistant. 
            You are working in a call center answering questions from users.
            Firstly, Please say 'Hello, I am an AI assistant. How can I help you?'.
        """
    elif current_role == 'RoleC':
        return """
            あなたは日本人のオペレーターです。
            ユーザーからの質問にわかりやすく丁寧に回答してください。
            また、最初は「お電話変わりました。オペレーターの山田です。ご要件をお伺いいたします。」
            と言ってください。
        """
    elif current_role == 'RoleD':
        return """
            You are English operator. 
            You are working in a call center answering questions from users.
            Please say 'Hello, I am operator Emma. How can I help you?'.
        """
    elif current_role == 'RoleE':
        return "「電話を終了しました。電話を切ってください。」と言ってください。"
    else:
        return """
            「コールセンターにお電話いただきありがとうございます。
            日本語の AI アシスタントと会話をする場合は 1 を、
            英語の AI アシスタントと会話をする場合は 2 を、
            日本人のオペレーターと会話をする場合は 3 を、
            アメリカ人のオペレーターと会話をする場合は 4 を、
            通話を終了する場合は 5 を入力してください。」
            と言ってください。
        """

async def send_instructions(gpt_client: RTLowLevelClient, instructions: str):
    """
    gpt_client を用いて共通のパラメータで指示を送信する。
    """
    await gpt_client.send(
        ResponseCreateMessage(
            response=ResponseCreateParams(
                modalities={"audio", "text"},
                instructions=instructions,
                voice="shimmer",
                output_audio_format="pcm16",
                input_audio_format="pcm16",
                input_audio_transcription={"model": "whisper-1"}
            )
        )
    )

async def start_conversation(call_id: str, conversation_state: dict):
    """
    RTLowLevelClient を用いて AI 会話を開始
    current_role に応じた指示を送信し、gpt_client を会話状態に保存
    """
    try:
        print_debug("start conversation")
        current_role = conversation_state.get('current_role')
        instructions = get_instructions(current_role)

        # GPT クライアントの初期化と接続
        deployment_name = AZURE_OPENAI_DEPLOYMENT_NAME
        gpt_client = RTLowLevelClient(
            url=AZURE_OPENAI_SERVICE_ENDPOINT,
            azure_deployment=deployment_name,
            key_credential=AzureKeyCredential(AZURE_OPENAI_SERVICE_KEY)
        )
        await gpt_client.connect()
        await send_instructions(gpt_client, instructions)
        conversation_state['gpt_client'] = gpt_client
        asyncio.create_task(receive_messages(call_id, conversation_state))
        print_debug(f"AI conversation started for call_id: {call_id}")
    except Exception as e:
        print_debug(f"Exception in start_conversation: {e}")

async def update_conversation(call_id: str, conversation_state: dict):
    """
    既存の gpt_client/websocket が有効な場合、一旦終了して新しい会話を開始することで最新の指示を送信
    """
    try:
        gpt_client = conversation_state.get('gpt_client')
        if gpt_client and not gpt_client.closed:
            print_debug(f"Closing gpt_client for call_id: {call_id}")
            conversation_state.pop('gpt_client', None)
            await gpt_client.close()
            print_debug(f"Update conversation for call_id: {call_id}")
        await start_conversation(call_id, conversation_state)
        print_debug(f"Conversation updated for call_id: {call_id}")
    except Exception as e:
        print_debug(f"Exception in update_conversation for call_id {call_id}: {e}")

async def process_websocket_message_async(call_id: str, message_text: str, conversation_state: dict):
    """
    Process an incoming WebSocket message.
    For audio data, encode into Base64 and append to the GPT client's input buffer.
    """
    try:
        message = json.loads(message_text)
        gpt_client = conversation_state.get('gpt_client')
        
        if message.get('kind') == 'AudioData':
            audio_data_base64 = message['audioData']['data']
            audio_data = base64.b64decode(audio_data_base64)
            if gpt_client:
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                await gpt_client.send(
                    InputAudioBufferAppendMessage(
                        type="input_audio_buffer.append",
                        audio=audio_base64
                    )
                )
            else:
                print_debug(f"gpt_client doesn't exist now for call_id: {call_id}. Waiting for creation.")
                await wait_for_gpt_client_initialization(call_id, conversation_state)
                print_debug(f"Created gpt_client for call_id: {call_id}")
                gpt_client = conversation_state.get('gpt_client')
                if gpt_client:
                    audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                    await gpt_client.send(
                        InputAudioBufferAppendMessage(
                            type="input_audio_buffer.append",
                            audio=audio_base64
                        )
                    )
                else:
                    print_debug(f"gpt_client is still not initialized for call_id: {call_id}")
        elif message.get('kind') == 'AudioMetadata':
            print_debug(f"Received AudioMetadata message for call_id: {call_id}")
        else:
            print_debug("Unknown message kind:", message.get('kind'))
    except Exception as e:
        print_debug(f"Exception in process_websocket_message_async for call_id {call_id}: {e}")

async def wait_for_gpt_client_initialization(call_id: str, conversation_state: dict):
    """
    Wait until the gpt_client is available in the conversation state.
    """
    retries = 10
    wait_time = 0.5  # seconds between attempts
    for _ in range(retries):
        await asyncio.sleep(wait_time)
        if conversation_state.get('gpt_client'):
            return

async def receive_messages(call_id: str, conversation_state: dict):
    """
    Continuously receive messages from the GPT client.
    Processes audio and transcript deltas.
    """
    try:
        gpt_client = conversation_state['gpt_client']
        # Initialize transcript buffer if not already present
        if 'transcript_buffer' not in conversation_state:
            conversation_state['transcript_buffer'] = ''
        while not gpt_client.closed:
            message = await gpt_client.recv()
            if message:
                if message.type == "response.audio.delta":
                    audio_data_base64 = message.delta
                    audio_data = base64.b64decode(audio_data_base64)
                    await receive_audio_for_outbound(call_id, audio_data, conversation_state)
                elif message.type == "response.audio_transcript.delta":
                    transcript_delta = message.delta
                    print_debug(f"Received transcript delta for call_id {call_id}: {transcript_delta}", log_level="debug")
                    conversation_state['transcript_buffer'] += transcript_delta
                    # Check for end-of-sentence punctuation to process transcript
                    if any(transcript_delta.endswith(punct) for punct in ['。', '！', '？', '.', '!', '?', '」', '\n']):
                        complete_sentence = conversation_state['transcript_buffer'].strip()
                        print_debug(f"Complete sentence for call_id {call_id}: {complete_sentence}")
                        conversation_state['transcript_buffer'] = ''
                elif message.type == "input.audio_transcript":
                    user_transcript = message.text
                    print_debug(f"User transcript for call_id {call_id}: {user_transcript}")
                elif message.type == "response.audio":
                    await receive_audio_for_outbound(call_id, message.data, conversation_state)
                elif message.type == "response.text":
                    print_debug(f"Received text response for call_id {call_id}: {message.text}")
    except Exception as e:
        print_debug(f"Exception in receive_messages for call_id {call_id}: {e}")

async def receive_audio_for_outbound(call_id: str, data: bytes, conversation_state: dict):
    """
    Send audio data outbound by encoding it in Base64 and sending it over the existing WebSocket.
    """
    if conversation_state:
        websocket = conversation_state.get('websocket')
        if websocket:
            audio_data_base64 = base64.b64encode(data).decode('utf-8')
            message = {
                "kind": "AudioData",
                "audioData": {
                    "timestamp": datetime.utcnow().isoformat() + 'Z',
                    "data": audio_data_base64,
                    "silent": False
                }
            }
            await websocket.send_text(json.dumps(message))
        else:
            print_debug(f"No active websocket for call_id: {call_id}")
    else:
        print_debug(f"No conversation state for call_id: {call_id}")
