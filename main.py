import os
import asyncio
import json
import uuid
import base64
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from azure.eventgrid import EventGridEvent, SystemEventNames
from azure.communication.callautomation import (
    CallAutomationClient,
    MediaStreamingOptions,
    AudioFormat,
    MediaStreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    PhoneNumberIdentifier,
    RecognizeInputType,
    TextSource
)
from azure.communication.callautomation.aio import CallAutomationClient as AsyncCallAutomationClient
# from azure.communication.callautomation import PlayOptions 
from azure.core.messaging import CloudEvent
from azure.communication.jobrouter import (
    JobRouterClient,
    JobRouterAdministrationClient
)
from azure.communication.jobrouter.models import (
    LongestIdleMode,
    RouterWorkerSelector,
    LabelOperator,
    RouterChannel,
    CloseJobOptions
)
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError 
# from rtclient import RTLowLevelClient, SessionUpdateMessage, ServerVAD, SessionUpdateParams, InputAudioTranscription
from rtclient import (
    ResponseCreateMessage,
    RTLowLevelClient,
    ResponseCreateParams,
    InputAudioBufferAppendMessage
)
from urllib.parse import urlencode

app = FastAPI()

# Configuration
load_dotenv()

ACS_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING")
CALLBACK_URI_HOST = os.getenv("CALLBACK_URI_HOST")
CALLBACK_EVENTS_URI = f"{CALLBACK_URI_HOST}/api/callbacks"
AZURE_OPENAI_SERVICE_ENDPOINT = os.getenv("AZURE_OPENAI_SERVICE_ENDPOINT")
AZURE_OPENAI_SERVICE_KEY = os.getenv("AZURE_OPENAI_SERVICE_KEY")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
WEBSOCKET_HOST = os.getenv("WEBSOCKET_HOST")

print("ACS_CONNECTION_STRING:", ACS_CONNECTION_STRING)
print("CALLBACK_URI_HOST:", CALLBACK_URI_HOST)
print("CALLBACK_EVENTS_URI:", CALLBACK_EVENTS_URI)
print("AZURE_OPENAI_SERVICE_ENDPOINT:", AZURE_OPENAI_SERVICE_ENDPOINT)
print("AZURE_OPENAI_SERVICE_KEY:", AZURE_OPENAI_SERVICE_KEY)
print("AZURE_OPENAI_DEPLOYMENT_NAME:", AZURE_OPENAI_DEPLOYMENT_NAME)

# Initialize clients
acs_client = AsyncCallAutomationClient.from_connection_string(ACS_CONNECTION_STRING)
router_admin_client = JobRouterAdministrationClient.from_connection_string(ACS_CONNECTION_STRING)
router_client = JobRouterClient.from_connection_string(ACS_CONNECTION_STRING)

# 会話状態を管理するためのディクショナリ  
conversation_states = {} 

# WebSocket client
# active_websocket = None
# websocket_connected = asyncio.Event()

# gpt_client = None  # ファイルの先頭付近で宣言  

# Create distribution policy
distribution_policy = router_admin_client.upsert_distribution_policy(
    distribution_policy_id="distribution-policy-1",
    offer_expires_after_seconds=60,
    mode=LongestIdleMode(),
    name="My distribution policy"
)

# Create queue
queue = router_admin_client.upsert_queue(
    queue_id="queue-1",
    name="My Queue",
    distribution_policy_id=distribution_policy.id
)

# Create worker
worker = router_client.upsert_worker(
    worker_id="worker-1",
    capacity=1,
    queues=["queue-1"],
    labels={
        "Some-Skill": 11
    },
    channels=[RouterChannel(channel_id="voice", capacity_cost_per_job=1)],
    available_for_offers=True
)

# Function to submit a job to the queue
async def submit_job_to_queue(job_id: str, channel_id: str, queue_id: str, priority: int):
    job = router_client.upsert_job(
        job_id=job_id,
        channel_id=channel_id,
        queue_id=queue_id,
        priority=priority,
        requested_worker_selectors=[
            RouterWorkerSelector(
                key="Some-Skill",
                label_operator=LabelOperator.GREATER_THAN,
                value=10
            )
        ]
    )
    print("Job submitted:", job)
    return job.id

@app.get("/")
async def read_root():
    print("Hello, world!")
    return PlainTextResponse("Hello, world!")

@app.post("/api/incomingCall")
async def incoming_call_handler(request: Request):
    print("Incoming call received")
    events = await request.json()
    print("events:", events)
    for event_dict in events:
        event = EventGridEvent.from_dict(event_dict)
        print("event:", event)
        if event.event_type == SystemEventNames.EventGridSubscriptionValidationEventName:
            validation_code = event.data['validationCode']
            print("Validation code:", validation_code)
            return JSONResponse(content={'validationResponse': validation_code})
        elif event.event_type == "Microsoft.Communication.IncomingCall":
            call_id = str(uuid.uuid4())  
            caller_id = event.data['from']['phoneNumber']['value'] if event.data['from']['kind'] == "phoneNumber" else event.data['from']['rawId']
            incoming_call_context = event.data['incomingCallContext']
            print("Caller ID:", caller_id)
            query_parameters = urlencode({"callerId": caller_id})
            callback_uri = f"{CALLBACK_EVENTS_URI}/{call_id}?{query_parameters}"
            websocket_url = f"wss://{WEBSOCKET_HOST}/ws/{call_id}"
            print("websocket_url:", websocket_url)

            media_streaming_options = MediaStreamingOptions(
                transport_url=websocket_url,
                transport_type=MediaStreamingTransportType.WEBSOCKET,
                content_type=MediaStreamingContentType.AUDIO,
                audio_channel_type=MediaStreamingAudioChannelType.MIXED,
                start_media_streaming=True,
                enable_bidirectional=True,
                audio_format=AudioFormat.PCM24_K_MONO
            )

            answer_call_result = await acs_client.answer_call(
                incoming_call_context=incoming_call_context,
                callback_url=callback_uri,
                media_streaming=media_streaming_options
            )

            # Wait for WebSocket connection to be established
            # await websocket_connected.wait()

            # Submit job to queue
            job_id = str(uuid.uuid4())
            submitted_job_id = await submit_job_to_queue(job_id, "voice", queue.id, priority=1)

            # Wait for the job offer and accept it
            asyncio.create_task(handle_job_offers(submitted_job_id))

            return Response(status_code=200)

@app.post("/api/callbacks/{contextId}")
async def handle_callback(contextId: str, request: Request):
    events = await request.json()
    print("Callback events:", events)
    for event_dict in events:
        event = CloudEvent.from_dict(event_dict)
        print("Callback event:", event)
        call_connection_id = event.data['callConnectionId']
        # if event.type == "Microsoft.Communication.CallConnected":
        #     print("Call connected")
        #     caller_id = request.query_params.get("callerId")
        #     await handle_recognize("Hello, thank you for calling! How can I help you today?", call_connection_id, caller_id)
        if event.type == "Microsoft.Communication.CallConnected":  
            print("Call connected")  
            # await play_initial_greeting(call_connection_id)  
            pass
        elif event.type == "Microsoft.Communication.RecognizeCompleted":
            print("Recognize completed")
            speech_text = event.data['speechResult']['speech']
            if speech_text:
                chat_gpt_response = await get_chat_gpt_response(speech_text)
                await handle_play(call_connection_id, chat_gpt_response)
        elif event.type == "Microsoft.Communication.MediaStreamingStarted":  
            print("Media streaming started")  
            pass
        elif event.type == "Microsoft.Communication.CallDisconnected":
            print("Call disconnected")
            await handle_hangup(call_connection_id)
    return Response(status_code=200)

# async def play_initial_greeting(call_connection_id: str):  
#     play_source = TextSource(text="こんにちは、お電話ありがとうございます。ご用件をお伺いできますか？", voice_name="ja-JP-NanamiNeural")  
#     try:  
#         # play_options = PlayOptions(interrupt_current_media_operation=True)  
#         # await acs_client.get_call_connection(call_connection_id).play_media_to_all(play_source, play_options=play_options)  
#         await acs_client.get_call_connection(call_connection_id).play_media_to_all(play_source)  
#     except Exception as e:  
#         print(f"Error playing initial greeting: {e}")  

# @app.websocket("/ws")
# async def websocket_endpoint(websocket: WebSocket):
#     print("WebSocket connection established")
#     await websocket.accept()
#     global active_websocket
#     active_websocket = websocket
#     websocket_connected.set()
#     await start_conversation()
#     while True:
#         data = await websocket.receive_text()
#         await process_websocket_message_async(data)

# @app.websocket("/ws")  
# async def websocket_endpoint(websocket: WebSocket):  
#     print("WebSocket connection established")  
#     await websocket.accept()  
#     global active_websocket  
#     active_websocket = websocket  
#     websocket_connected.set()  
#     await start_conversation()  
#     while True:  
#         message = await websocket.receive()  
#         if 'bytes' in message:  
#             data = message['bytes']  
#             await process_websocket_message_async(data)  

# @app.websocket("/ws")  
# async def websocket_endpoint(websocket: WebSocket):  
#     print("WebSocket connection established")  
#     await websocket.accept()  
#     global active_websocket  
#     active_websocket = websocket  
#     websocket_connected.set()  
#     await start_conversation()  
#     try:  
#         while True:  
#             message = await websocket.receive()  
#             if message['type'] == 'websocket.receive':  
#                 if 'text' in message:  
#                     text_data = message['text']  
#                     await process_websocket_message_async(text_data)  
#                 elif 'bytes' in message:  
#                     data = message['bytes']  
#                     # 必要に応じて処理  
#             elif message['type'] == 'websocket.disconnect':  
#                 print("WebSocket disconnected")  
#                 break  
#     except Exception as e:  
#         print(f"Exception in websocket_endpoint: {e}")  
#     finally:  
#         active_websocket = None  
#         print("Connection closed")  

@app.websocket("/ws/{call_id}")  
async def websocket_endpoint(websocket: WebSocket, call_id: str):  
    print("WebSocket connection established")  
    await websocket.accept()  
    # このコールに対応する状態を初期化  
    conversation_state = {  
        'websocket': websocket,  
        'gpt_client': None  
    }  
    conversation_states[call_id] = conversation_state  
  
    await start_conversation(call_id)  # コールごとの会話を開始  
    try:  
        while True:  
            message = await websocket.receive()  
            if message['type'] == 'websocket.receive':  
                if 'text' in message:  
                    text_data = message['text']  
                    await process_websocket_message_async(call_id, text_data)  
                elif 'bytes' in message:  
                    data = message['bytes']  
                    # 必要に応じて処理  
            elif message['type'] == 'websocket.disconnect':  
                print("WebSocket disconnected")  
                break  
    except Exception as e:  
        print(f"Exception in websocket_endpoint: {e}")  
    finally:  
        if conversation_state['gpt_client']:  
            await conversation_state['gpt_client'].disconnect()  
            conversation_state['gpt_client'] = None  
        del conversation_states[call_id]  
        print(f"Connection closed for call_id: {call_id}") 

# async def handle_recognize(reply_text: str, call_connection_id: str, caller_id: str):
#     play_source = TextSource(text=reply_text, voice_name="en-US-NancyNeural")
#     target_participant = PhoneNumberIdentifier(caller_id)
#     connection_client = acs_client.get_call_connection(call_connection_id)
#     try:
#         await connection_client.start_recognizing_media(
#             input_type=RecognizeInputType.SPEECH,
#             play_prompt=play_source,
#             end_silence_timeout=10,
#             target_participant=target_participant
#         )
#     except ResourceNotFoundError:
#         print(f"Call with connection ID {call_connection_id} not found. It may have already been terminated.")

async def handle_play(call_connection_id: str, text_to_play: str):
    play_source = TextSource(text=text_to_play, voice_name="en-US-NancyNeural")
    await acs_client.get_call_connection(call_connection_id).play_media_to_all(play_source)

async def handle_hangup(call_connection_id: str):
    try:
        await acs_client.get_call_connection(call_connection_id).hang_up(is_for_everyone=True)
    except ResourceNotFoundError:
        print(f"Call with connection ID {call_connection_id} not found. It may have already been terminated.")

# async def get_chat_gpt_response(speech_input: str) -> str:
#     client = RTLowLevelClient(
#         url=AZURE_OPENAI_SERVICE_ENDPOINT,
#         key_credential=AzureKeyCredential(AZURE_OPENAI_SERVICE_KEY),
#         azure_deployment=AZURE_OPENAI_DEPLOYMENT_NAME
#     )
#     await client.connect()
#     await client.send(
#         SessionUpdateMessage(
#             session=SessionUpdateParams(
#                 instructions="You are an AI assistant that helps people find information.",
#                 turn_detection=ServerVAD(type="server_vad"),
#                 voice='shimmer',
#                 input_audio_format='pcm16',
#                 output_audio_format='pcm16',
#                 input_audio_transcription=InputAudioTranscription(model="whisper-1")
#             )
#         )
#     )
#     response = await client.recv()
#     return response.transcript if response else "Sorry, I didn't understand that."

async def get_chat_gpt_response(speech_input: str) -> str:
    async with RTLowLevelClient(
        url=AZURE_OPENAI_SERVICE_ENDPOINT,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT_NAME,
        key_credential=AzureKeyCredential(AZURE_OPENAI_SERVICE_KEY)
    ) as client:
        await client.send(
            ResponseCreateMessage(
                response=ResponseCreateParams(
                    modalities={"audio", "text"},
                    instructions="You are an AI assistant that helps people find information."
                )
            )
        )
        done = False
        transcript = ""
        while not done:
            message = await client.recv()
            match message.type:
                case "response.done":
                    done = True
                case "error":
                    done = True
                    print(message.error)
                case "response.audio_transcript.delta":
                    transcript += message.delta
                case _:
                    pass
        return transcript if transcript else "Sorry, I didn't understand that."

# async def start_conversation():
#     client = RTLowLevelClient(
#         url=AZURE_OPENAI_SERVICE_ENDPOINT,
#         key_credential=AzureKeyCredential(AZURE_OPENAI_SERVICE_KEY),
#         azure_deployment=AZURE_OPENAI_DEPLOYMENT_NAME
#     )
#     await client.connect()
#     await client.send(
#         SessionUpdateMessage(
#             session=SessionUpdateParams(
#                 instructions="You are an AI assistant that helps people find information.",
#                 turn_detection=ServerVAD(type="server_vad"),
#                 voice='shimmer',
#                 input_audio_format='pcm16',
#                 output_audio_format='pcm16',
#                 input_audio_transcription=InputAudioTranscription(model="whisper-1")
#             )
#         )
#     )
#     asyncio.create_task(receive_messages(client))

# async def start_conversation():
#     async with RTLowLevelClient(
#         url=AZURE_OPENAI_SERVICE_ENDPOINT,
#         azure_deployment=AZURE_OPENAI_DEPLOYMENT_NAME,
#         key_credential=AzureKeyCredential(AZURE_OPENAI_SERVICE_KEY)
#     ) as client:
#         await client.send(
#             ResponseCreateMessage(
#                 response=ResponseCreateParams(
#                     modalities={"audio", "text"},
#                     instructions="You are an AI assistant that helps people find information.",
#                     voice="alloy"
#                 )
#             )
#         )
#         asyncio.create_task(receive_messages(client))

async def start_conversation(call_id: str):  
    try:  
        gpt_client = RTLowLevelClient(  
            url=AZURE_OPENAI_SERVICE_ENDPOINT,  
            azure_deployment=AZURE_OPENAI_DEPLOYMENT_NAME,  
            key_credential=AzureKeyCredential(AZURE_OPENAI_SERVICE_KEY)  
        )  
        await gpt_client.connect()  
        await gpt_client.send(  
            ResponseCreateMessage(  
                response=ResponseCreateParams(  
                    modalities={"audio", "text"},  
                    instructions="あなたはユーザーからの質問に答えるコールセンターに勤める AI アシスタントです。まず最初に「お電話ありがとうございます。ご用件をお伺いできますか？」と話しかけてください。",  
                    voice="shimmer", 
                    output_audio_format="pcm16",
                    input_audio_format="pcm16", 
                    input_audio_transcription={"model": "whisper-1"} 
                )   
            )  
        )  
        # asyncio.create_task(receive_messages(gpt_client))  
        # print("AI conversation started")  
        # gpt_client を保存  
        conversation_states[call_id]['gpt_client'] = gpt_client  
        asyncio.create_task(receive_messages(call_id))  
        print(f"AI conversation started for call_id: {call_id}")  
    except Exception as e:  
        print(f"Exception in start_conversation: {e}")  

# async def process_websocket_message_async(data: str):
#     if active_websocket:
#         await active_websocket.send_text(data)

# async def process_websocket_message_async(data: bytes):  
#     if gpt_client:  
#         await gpt_client.send_audio(data)  

# async def process_websocket_message_async(message_text: str):  
#     try:  
#         message = json.loads(message_text)  
#         # print("Received message:", message)
#         if message.get('kind') == 'AudioData':
#             audio_data_base64 = message['audioData']['data']  
#             audio_data = base64.b64decode(audio_data_base64)  
#             if gpt_client:  
#                 # await gpt_client.send_audio(audio_data)
#                 # バイト列をBase64エンコードして文字列に変換  
#                 audio_base64 = base64.b64encode(audio_data).decode('utf-8')   
#                 await gpt_client.send(  
#                     InputAudioBufferAppendMessage(  
#                         type="input_audio_buffer.append",  
#                         audio=audio_base64
#                     )  
#                 )  
#         # if message.get('type') == 'AudioMediaReceived':  
#         #     audio_data_base64 = message['data']  
#         #     audio_data = base64.b64decode(audio_data_base64)  
#         #     if gpt_client:  
#         #         await gpt_client.send_audio(audio_data)  
#     except Exception as e:  
#         print(f"Exception in process_websocket_message_async: {e}")  

async def process_websocket_message_async(call_id: str, message_text: str):  
    try:  
        message = json.loads(message_text)  
        # print("Received message:", message)
        if message.get('kind') == 'AudioData':
            audio_data_base64 = message['audioData']['data']  
            audio_data = base64.b64decode(audio_data_base64) 
            gpt_client = conversation_states[call_id]['gpt_client']   
            if gpt_client:  
                # await gpt_client.send_audio(audio_data)
                # バイト列をBase64エンコードして文字列に変換  
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')   
                await gpt_client.send(  
                    InputAudioBufferAppendMessage(  
                        type="input_audio_buffer.append",  
                        audio=audio_base64
                    )  
                )  
            else:  
                print(f"gpt_client is not initialized for call_id: {call_id}")  
        # if message.get('type') == 'AudioMediaReceived':  
        #     audio_data_base64 = message['data']  
        #     audio_data = base64.b64decode(audio_data_base64)  
        #     if gpt_client:  
        #         await gpt_client.send_audio(audio_data) 
        else:  
            print("Unknown message kind:", message.get('kind'))  
    except Exception as e:  
        print(f"Exception in process_websocket_message_async for call_id {call_id}: {e}") 

# async def receive_messages(client: RTLowLevelClient):  
#     try:  
#         while not client.closed:  
#             message = await client.recv()  
#             if message:  
#                 print(f"Received message from AI: {message}") 
#                 if message.type == "response.audio.delta":  
#                     # 音声データの delta を処理  
#                     audio_data_base64 = message.delta  
#                     audio_data = base64.b64decode(audio_data_base64)  
#                     await receive_audio_for_outbound(audio_data)  
#                 elif message.type == "response.audio_transcript.delta":  
#                     # テキストの delta を処理  
#                     transcript_delta = message.delta  
#                     print(f"Received transcript delta: {transcript_delta}")    
#                 elif message.type == "response.audio":  
#                     await receive_audio_for_outbound(message.data)  
#                 elif message.type == "response.text":  
#                     # テキストレスポンスの処理（必要に応じて）  
#                     print(f"Received text response: {message.text}") 
#     except Exception as e:  
#         print(f"Exception in receive_messages: {e}")  

async def receive_messages(call_id: str):  
    try:  
        gpt_client = conversation_states[call_id]['gpt_client']  
        while not gpt_client.closed:  
            message = await gpt_client.recv()  
            if message:  
                print(f"Received message from AI for call_id {call_id}: {message}")  
                if message.type == "response.audio.delta":  
                    # 音声データの delta を処理  
                    audio_data_base64 = message.delta  
                    audio_data = base64.b64decode(audio_data_base64)  
                    await receive_audio_for_outbound(call_id, audio_data)  
                elif message.type == "response.audio_transcript.delta":  
                    # テキストの delta を処理  
                    transcript_delta = message.delta  
                    print(f"Received transcript delta for call_id {call_id}: {transcript_delta}")    
                elif message.type == "response.audio":  
                    await receive_audio_for_outbound(call_id, message.data)  
                elif message.type == "response.text":  
                    # テキストレスポンスの処理（必要に応じて）  
                    print(f"Received text response for call_id {call_id}: {message.text}")   
    except Exception as e:  
        print(f"Exception in receive_messages for call_id {call_id}: {e}")  

# async def receive_audio_for_outbound(data: str):
#     if active_websocket:
#         await active_websocket.send_text(json.dumps({"Kind": "AudioData", "AudioData": {"Data": data}}))

# async def receive_audio_for_outbound(data: bytes):  
#     if active_websocket:  
#         await active_websocket.send_bytes(data)  

# async def receive_audio_for_outbound(data: bytes):  
#     if active_websocket:  
#         audio_data_base64 = base64.b64encode(data).decode('utf-8')  
#         message = {  
#             "type": "AudioMedia",  
#             "data": audio_data_base64  
#         }  
#         await active_websocket.send_text(json.dumps(message))  

# async def receive_audio_for_outbound(data: bytes):  
#     if active_websocket:  
#         audio_data_base64 = base64.b64encode(data).decode('utf-8')  
#         message = {  
#             "kind": "AudioData",
#             "audioData": {  
#                 "timestamp": datetime.utcnow().isoformat() + 'Z', 
#                 "data": audio_data_base64,  
#                 "silent": False 
#             }  
#         }  
#         await active_websocket.send_text(json.dumps(message))  

async def receive_audio_for_outbound(call_id: str, data: bytes):  
    conversation_state = conversation_states.get(call_id)  
    if conversation_state:
        websocket = conversation_state['websocket']
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
            print(f"No active websocket for call_id: {call_id}")  
    else:  
        print(f"No conversation state for call_id: {call_id}") 

# Function to handle job offers and accept them
async def handle_job_offers(job_id: str):
    while True:
        try:
            await asyncio.sleep(10)
            worker = router_client.get_worker(worker_id="worker-1")
            if worker is not None:
                for offer in worker.offers:
                    if offer.job_id == job_id:  # 特定のジョブ ID に対するオファーを確認
                        print(f"Worker {worker.id} has an active offer for job {offer.job_id}")
                        accept = router_client.accept_job_offer(worker_id=worker.id, offer_id=offer.offer_id)
                        print(f"Worker {worker.id} is assigned job {accept.job_id}")
                        await handle_job_completion(accept.job_id, accept.assignment_id)
                        return  # ジョブが割り当てられたらループを終了
            else:
                print("Worker not found or not initialized.")
        except Exception as e:
            print(f"Error in handle_job_offers: {e}")

# Function to handle job completion
async def handle_job_completion(job_id: str, assignment_id: str):
    router_client.complete_job(job_id=job_id, assignment_id=assignment_id)
    print(f"Job {job_id} completed")
    router_client.close_job(job_id=job_id, assignment_id=assignment_id, options=CloseJobOptions(disposition_code="Resolved"))
    print(f"Job {job_id} closed")
    router_client.delete_job(job_id)
    print(f"Job {job_id} deleted")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
