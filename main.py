import os
import asyncio
import json
import uuid
import base64
from datetime import datetime
from dotenv import load_dotenv
from urllib.parse import urlencode
from contextlib import asynccontextmanager
from urllib.parse import urlencode, urlparse
from fastapi import FastAPI, WebSocket, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from rtclient import (
    ResponseCreateMessage,
    RTLowLevelClient,
    ResponseCreateParams,
    InputAudioBufferAppendMessage
)
from azure.eventgrid import EventGridEvent, SystemEventNames
from azure.core.messaging import CloudEvent
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ResourceNotFoundError 
from azure.communication.callautomation import (
    MediaStreamingOptions,
    AudioFormat,
    MediaStreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    DtmfTone,
    CommunicationUserIdentifier,   
    PhoneNumberIdentifier,  
    MicrosoftTeamsUserIdentifier,  
    UnknownIdentifier,
)
from azure.communication.callautomation.aio import CallAutomationClient as AsyncCallAutomationClient
from azure.communication.jobrouter.aio import JobRouterClient as AsyncJobRouterClient  
from azure.communication.jobrouter.aio import JobRouterAdministrationClient as AsyncJobRouterAdministrationClient  
from azure.communication.jobrouter.models import (
    LongestIdleMode,
    RouterWorkerSelector,
    LabelOperator,
    RouterChannel,
    CloseJobOptions,
)

# Configuration
load_dotenv()

ACS_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING")
CALLBACK_URI_HOST = os.getenv("CALLBACK_URI_HOST")
CALLBACK_EVENTS_URI = f"{CALLBACK_URI_HOST}/api/callbacks"
AZURE_OPENAI_SERVICE_ENDPOINT = os.getenv("AZURE_OPENAI_SERVICE_ENDPOINT")
AZURE_OPENAI_SERVICE_KEY = os.getenv("AZURE_OPENAI_SERVICE_KEY")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

# ログレベルの設定
print_log_level = "info" # None or "info" or "debug"
log_levels = {None: 0, "info": 1, "debug": 2}

# デバッグメッセージを出力する関数
def print_debug(*msg, log_level="info"):
    if log_levels.get(log_level, -1) <= log_levels.get(print_log_level, -1):
        print(*msg)

print_debug("ACS_CONNECTION_STRING:", ACS_CONNECTION_STRING, log_level="debug")
print_debug("CALLBACK_URI_HOST:", CALLBACK_URI_HOST, log_level="debug")
print_debug("CALLBACK_EVENTS_URI:", CALLBACK_EVENTS_URI, log_level="debug")
print_debug("AZURE_OPENAI_SERVICE_ENDPOINT:", AZURE_OPENAI_SERVICE_ENDPOINT, log_level="debug")
print_debug("AZURE_OPENAI_SERVICE_KEY:", AZURE_OPENAI_SERVICE_KEY, log_level="debug")
print_debug("AZURE_OPENAI_DEPLOYMENT_NAME:", AZURE_OPENAI_DEPLOYMENT_NAME, log_level="debug")

# Initialize clients
acs_client = AsyncCallAutomationClient.from_connection_string(ACS_CONNECTION_STRING)
router_admin_client = AsyncJobRouterAdministrationClient.from_connection_string(ACS_CONNECTION_STRING)  
router_client = AsyncJobRouterClient.from_connection_string(ACS_CONNECTION_STRING) 

# 会話状態を管理するためのディクショナリ  
conversation_states = {} 

# job_id から call_id へのマッピングを保存  
job_id_to_call_id = {} 
 
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:  
        # Distribution Policy の作成    
        app.state.distribution_policy = await router_admin_client.upsert_distribution_policy(    
            distribution_policy_id="distribution-policy-1",    
            offer_expires_after_seconds=60,    
            mode=LongestIdleMode(),    
            name="My distribution policy"   
        )    

        # キューの作成    
        app.state.queue = await router_admin_client.upsert_queue(    
            queue_id="queue-1",    
            name="My Queue",    
            distribution_policy_id=app.state.distribution_policy.id    
        )    

        # ワーカーの作成   
        app.state.worker0 = await router_client.upsert_worker(    
            worker_id="worker-0",    
            capacity=10,
            queues=["queue-1"],
            labels={"Some-Skill": "10", "Role": "RoleDefault"}, 
            channels=[RouterChannel(  
                channel_id="voice",  
                capacity_cost_per_job=1,  
            )], 
            available_for_offers=True 
        )     

        app.state.worker1 = await router_client.upsert_worker(    
            worker_id="worker-1",    
            capacity=10,
            queues=["queue-1"],
            labels={"Some-Skill": "11", "Role": "RoleA"},
            channels=[RouterChannel(  
                channel_id="voice",  
                capacity_cost_per_job=1,  
            )], 
            available_for_offers=True 
        )    

        app.state.worker2 = await router_client.upsert_worker(    
            worker_id="worker-2",    
            capacity=10,    
            queues=["queue-1"],    
            labels={"Some-Skill": "12", "Role": "RoleB"},    
            channels=[RouterChannel(  
                channel_id="voice",  
                capacity_cost_per_job=1,  
            )],    
            available_for_offers=True
        )    

        app.state.worker3 = await router_client.upsert_worker(    
            worker_id="worker-3",    
            capacity=10,    
            queues=["queue-1"],    
            labels={"Some-Skill": "13", "Role": "RoleC"},    
            channels=[RouterChannel(  
                channel_id="voice",  
                capacity_cost_per_job=1,  
            )],    
            available_for_offers=True
        )    

        app.state.worker4 = await router_client.upsert_worker(    
            worker_id="worker-4",    
            capacity=10,    
            queues=["queue-1"],    
            labels={"Some-Skill": "14", "Role": "RoleD"},    
            channels=[RouterChannel(  
                channel_id="voice",  
                capacity_cost_per_job=1,  
            )],    
            available_for_offers=True
        )    

        app.state.worker5 = await router_client.upsert_worker(    
            worker_id="worker-5",    
            capacity=10,    
            queues=["queue-1"],    
            labels={"Some-Skill": "15", "Role": "RoleE"},    
            channels=[RouterChannel(  
                channel_id="voice",  
                capacity_cost_per_job=1,  
            )],    
            available_for_offers=True
        )    
        yield

    except Exception as e:  
        print_debug(f"Error in startup_event: {e}")  

app = FastAPI(lifespan = lifespan)

async def submit_job_to_queue(job_id: str, channel_id: str, queue_id: str, priority: int, role_label: str):  
    job = await router_client.upsert_job(  
        job_id=job_id,  
        channel_id=channel_id,  
        queue_id=queue_id,  
        priority=priority,  
        requested_worker_selectors=[  
            RouterWorkerSelector(  
                key="Role",  
                label_operator=LabelOperator.EQUAL,
                value=role_label  
            )  
        ]
    )  
    print_debug("Job submitted:", job, log_level = "debug")  
    return job.id  

@app.get("/")
async def read_root():
    print_debug("Hello, world!")
    return PlainTextResponse("Hello, world!")

@app.post("/api/incomingCall")
async def incoming_call_handler(request: Request):
    print_debug("Incoming call received")
    events = await request.json()
    print_debug("events:", events, log_level="debug")
    for event_dict in events:
        event = EventGridEvent.from_dict(event_dict)
        print_debug("event:", event, log_level="debug")
        if event.event_type == SystemEventNames.EventGridSubscriptionValidationEventName:
            validation_code = event.data['validationCode']
            print_debug("Validation code:", validation_code)
            return JSONResponse(content={'validationResponse': validation_code})
        elif event.event_type == "Microsoft.Communication.IncomingCall":
            call_id = str(uuid.uuid4())  
            caller_id = event.data['from']['phoneNumber']['value'] if event.data['from']['kind'] == "phoneNumber" else event.data['from']['rawId']
            incoming_call_context = event.data['incomingCallContext']
            print_debug("Caller ID:", caller_id)
            query_parameters = urlencode({"callerId": caller_id})
            callback_uri = f"{CALLBACK_EVENTS_URI}/{call_id}?{query_parameters}"
            parsed_url = urlparse(CALLBACK_EVENTS_URI)
            websocket_url = f"wss://{parsed_url.netloc}/ws/{call_id}"
            print_debug("websocket_url:", websocket_url)

            media_streaming_options = MediaStreamingOptions(
                transport_url=websocket_url,
                transport_type=MediaStreamingTransportType.WEBSOCKET,
                content_type=MediaStreamingContentType.AUDIO,
                audio_channel_type=MediaStreamingAudioChannelType.MIXED,
                start_media_streaming=True,
                # start_media_streaming=False,
                enable_bidirectional=True,
                audio_format=AudioFormat.PCM24_K_MONO
            )

            answer_call_result = await acs_client.answer_call(
                incoming_call_context=incoming_call_context,
                operation_context="incomingCall",
                callback_url=callback_uri,
                media_streaming=media_streaming_options,
            )

            selected_role = "RoleDefault"

            # Submit job to queue
            job_id = str(uuid.uuid4())
            submitted_job_id = await submit_job_to_queue(job_id, "voice", app.state.queue.id, priority=1, role_label=selected_role)

            # コールとジョブのマッピングを保存  
            job_id_to_call_id[job_id] = call_id
            print_debug("Job ID to call ID mapping:", job_id_to_call_id)

            # 発信者の CommunicationIdentifier を取得  
            caller = parse_communication_identifier(event.data['from'])  

            # 会話状態を初期化  
            conversation_states[call_id] = {  
                'call_id': call_id,  
                'job_id': job_id,  
                'caller_id': caller_id,  
                'caller_communication_identifier': caller, 
                'media_streaming_options': media_streaming_options,
                'websocket_ready': False,
                'current_role': None
            }  
            print_debug("Conversation states:", conversation_states)

            # Wait for the job offer and accept it
            asyncio.create_task(handle_job_offers(submitted_job_id))

            return Response(status_code=200)

@app.post("/api/callbacks/{call_id}")
async def handle_callback(call_id: str, request: Request):
    events = await request.json()
    print_debug("Callback events:", events, log_level = "debug")
    for event_dict in events:
        event = CloudEvent.from_dict(event_dict)
        print_debug("Callback event:", event, log_level = "debug")
        call_connection_id = event.data['callConnectionId']
        if event.type == "Microsoft.Communication.CallConnected":  
            print_debug("Call connected")  
            # DTMF 認識を開始  
            await start_dtmf_recognition(call_connection_id, call_id)  
        elif event.type == "Microsoft.Communication.ContinuousDtmfRecognitionToneReceived":  
            conversation_state = conversation_states.get(call_id)
            tone = event.data['tone']
            previous_job_id = conversation_state.get('job_id')  
            previous_assignment_id = conversation_state.get('assignment_id')  
            if tone == DtmfTone.ONE.value:
                print_debug("Tone 1 received")
                conversation_state['current_role'] = 'RoleA'
            elif tone == DtmfTone.TWO.value:
                print_debug("Tone 2 received")
                conversation_state['current_role'] = 'RoleB'
            elif tone == DtmfTone.THREE.value:
                print_debug("Tone 3 received")
                conversation_state['current_role'] = 'RoleC'
            elif tone == DtmfTone.FOUR.value:
                print_debug("Tone 4 received")
                conversation_state['current_role'] = 'RoleD'
            elif tone == DtmfTone.FIVE.value:
                print_debug("Tone 5 received")
                conversation_state['current_role'] = 'RoleE'
            else:  
                print_debug(f"Received unhandled DTMF tone: {tone}") 

            # 以前のジョブのアサインメントを解放（必要に応じて）  
            previous_job_id = conversation_state.get('job_id')  
            if previous_job_id and previous_assignment_id:    
                await handle_job_completion(previous_job_id, previous_assignment_id)
                # 会話状態から以前のジョブ情報を削除  
                conversation_state.pop('job_id', None)  
                conversation_state.pop('assignment_id', None)  
            elif previous_job_id and previous_assignment_id is None:  
                # assignment_id が取得されていない場合、フラグを立てる  
                conversation_state['pending_job_completion'] = True  
                print_debug("Pending job completion due to missing assignment_id")  
            else:  
                print_debug("Cannot complete previous job: assignment_id is None")  

            # 新しいジョブを作成してキューに送信  
            new_job_id = str(uuid.uuid4())  
            conversation_state['job_id'] = new_job_id  # 新しいジョブIDを保存  

            submitted_job_id = await submit_job_to_queue(  
                new_job_id,  
                "voice",  
                app.state.queue.id,  
                priority=1,  
                role_label=conversation_state['current_role']  
            )  
        
            # コールとジョブのマッピングを更新  
            job_id_to_call_id[new_job_id] = call_id  
            print_debug("Job ID to call ID mapping:", job_id_to_call_id)  
        
            # ジョブオファーを処理するタスクを開始  
            asyncio.create_task(handle_job_offers(submitted_job_id))  

        elif event.type == "Microsoft.Communication.RecognizeCompleted":
            print_debug("Recognize completed") 
        elif event.type == "Microsoft.Communication.MediaStreamingStarted":  
            print_debug("Media streaming started")  
        elif event.type == "Microsoft.Communication.CallDisconnected":
            print_debug("Call disconnected")
            await handle_hangup(call_connection_id)
    return Response(status_code=200)

@app.websocket("/ws/{call_id}")  
async def websocket_endpoint(websocket: WebSocket, call_id: str):  
    print_debug("WebSocket connection established")  
    await websocket.accept()  

    conversation_state = conversation_states.get(call_id) 
    if conversation_state is None:
        # このコールに対応する状態を初期化  
        conversation_state = {  
            'websocket': websocket,  
            'gpt_client': None,
            'websocket_ready': True
        }  
        conversation_states[call_id] = conversation_state 
    else:  
        conversation_state['websocket'] = websocket  
        conversation_state['websocket_ready'] = True

    print("conversation_state:", conversation_state)

    # ワーカーがすでに割り当てられていれば会話を開始  
    if 'assigned_worker' in conversation_state:  
        await start_conversation(call_id)  
  
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
                print_debug("WebSocket disconnected")  
                break  
    except Exception as e:  
        print_debug(f"Exception in websocket_endpoint: {e}")  
    finally:  
        if conversation_state['gpt_client']:  
            await conversation_state['gpt_client'].close() 
            conversation_state['gpt_client'] = None  
        del conversation_states[call_id]  
        print_debug(f"Connection closed for call_id: {call_id}") 

async def start_dtmf_recognition(call_connection_id: str, call_id: str):  
    print_debug(f"Starting DTMF recognition for call_id {call_id}")  
    try:  
        conversation_state = conversation_states.get(call_id)    
        if not conversation_state:    
            print_debug(f"No conversation state found for call_id {call_id}")    
            return  
          
        # DTMF 認識が進行中か確認  
        if conversation_state.get('dtmf_recognition_in_progress', False):  
            print_debug(f"DTMF recognition already in progress for call_id {call_id}")  
            return  
          
        # フラグを設定  
        conversation_state['dtmf_recognition_in_progress'] = True  
        call_connection = acs_client.get_call_connection(call_connection_id)
        target_participant = conversation_state['caller_communication_identifier'] 
        operation_context = f"dtmf_{call_id}_{uuid.uuid4()}"   

        await call_connection.start_continuous_dtmf_recognition(
            target_participant=target_participant,
            operation_context="dtmf-reco-on-c2",
        )

        print_debug(f"DTMF recognition started for call_id {call_id} with operation_context {operation_context}.")  
  
    except Exception as e:  
        print_debug(f"Error starting DTMF recognition for call_id {call_id}: {e}")  
        # エラー時にフラグをリセット  
        conversation_state['dtmf_recognition_in_progress'] = False  

async def handle_hangup(call_connection_id: str):
    try:
        await acs_client.get_call_connection(call_connection_id).hang_up(is_for_everyone=True)
    except ResourceNotFoundError:
        print_debug(f"Call with connection ID {call_connection_id} not found. It may have already been terminated.")

# CommunicationIdentifier をパースする関数を定義  
def parse_communication_identifier(data):  
    kind = data.get('kind')  
    raw_id = data.get('rawId')  
    if kind == 'communicationUser':  
        return CommunicationUserIdentifier(data['communicationUser']['id'])  
    elif kind == 'phoneNumber':  
        return PhoneNumberIdentifier(data['phoneNumber']['value'])  
    elif kind == 'microsoftTeamsUser':  
        msteam_user = data['microsoftTeamsUser']  
        return MicrosoftTeamsUserIdentifier(user_id=msteam_user['userId'], is_anonymous=msteam_user['isAnonymous'], cloud=msteam_user['cloud'])  
    else:  
        return UnknownIdentifier(raw_id)  

async def start_conversation(call_id: str):  
    try:  
        print("start conversation")
        conversation_state = conversation_states[call_id]  
        assigned_worker = conversation_state.get('assigned_worker')  

        # 割り当てられたワーカーのロールに基づいて指示を設定  
        if assigned_worker:  
            worker_role_label = assigned_worker.labels.get('Role', 'DefaultRole')  
            print_debug(f"Worker role label: {worker_role_label}")
  
        # ワーカーの 'Role' ラベルに応じて指示を変更
        if conversation_state['current_role'] == 'RoleA':  
            instructions = """
                あなたは日本語の AI アシスタントです。
                ユーザーからの質問にわかりやすく丁寧に回答してください。
                また、最初は「お電話変わりました。AI アシスタントです。ご要件をお伺いいたします。」
                と言ってください。
            """ 
        elif conversation_state['current_role'] == 'RoleB':  
            instructions = """
                You are English AI assistant. 
                You are working in a call center answering questions from users.
                Firstly, Please say 'Hello, I am an AI assistant. How can I help you?'.
            """
        elif conversation_state['current_role'] == 'RoleC':  
            instructions = """
                あなたは日本人のオペレーターです。
                ユーザーからの質問にわかりやすく丁寧に回答してください。
                また、最初は「お電話変わりました。オペレーターの山田です。ご要件をお伺いいたします。」
                と言ってください。
            """  
        elif conversation_state['current_role'] == 'RoleD':  
            instructions = """
                You are English operator. 
                You are working in a call center answering questions from users.
                Please say 'Hello, I am operator Emma. How can I help you?'.
            """
        elif conversation_state['current_role'] == 'RoleE':  
            instructions = "「電話を終了しました。電話を切ってください。」と言ってください。"  
        else:  
            instructions = """
                「コールセンターにお電話いただきありがとうございます。
                日本語の AI アシスタントと会話をする場合は 1 を、
                英語の AI アシスタントと会話をする場合は 2 を、
                日本人のオペレーターと会話をする場合は 3 を、
                アメリカ人のオペレーターと会話をする場合は 4 を、
                通話を終了する場合は 5 を入力してください。」
                と言ってください。
            """   
        deployment_name = AZURE_OPENAI_DEPLOYMENT_NAME  

        gpt_client = RTLowLevelClient(  
            url=AZURE_OPENAI_SERVICE_ENDPOINT,  
            azure_deployment=deployment_name,  
            key_credential=AzureKeyCredential(AZURE_OPENAI_SERVICE_KEY)  
        )  
        await gpt_client.connect()  
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
        # gpt_client を保存  
        conversation_states[call_id]['gpt_client'] = gpt_client  
        asyncio.create_task(receive_messages(call_id))  
        print_debug(f"AI conversation started for call_id: {call_id}")  
    except Exception as e:  
        print_debug(f"Exception in start_conversation: {e}")  

async def process_websocket_message_async(call_id: str, message_text: str):  
    try:  
        message = json.loads(message_text)  
        if message.get('kind') == 'AudioData':
            audio_data_base64 = message['audioData']['data']  
            audio_data = base64.b64decode(audio_data_base64) 
            conversation_state = conversation_states[call_id] 
            gpt_client = conversation_state.get('gpt_client') 

            if gpt_client:  
                # バイト列をBase64エンコードして文字列に変換  
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')   
                await gpt_client.send(  
                    InputAudioBufferAppendMessage(  
                        type="input_audio_buffer.append",  
                        audio=audio_base64
                    )  
                )  
            else:  
                # gpt_clientが初期化されるまで待機  
                print_debug(f"gpt_client is not initialized yet for call_id: {call_id}. Waiting for initialization.")  
                await wait_for_gpt_client_initialization(call_id)  
                # 再度取得  
                gpt_client = conversation_states[call_id].get('gpt_client')  
                if gpt_client:  
                    # バイト列をBase64エンコードして文字列に変換  
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
            pass  
        else:  
            print_debug("Unknown message kind:", message.get('kind'))  
    except Exception as e:  
        print_debug(f"Exception in process_websocket_message_async for call_id {call_id}: {e}") 

# gpt_clientの初期化を待つための関数  
async def wait_for_gpt_client_initialization(call_id: str):  
    conversation_state = conversation_states[call_id]  
    retries = 10  
    wait_time = 0.5  # 0.5秒ごとにチェック  
    for _ in range(retries):  
        await asyncio.sleep(wait_time)  
        if conversation_state.get('gpt_client'):  
            return  
        
async def receive_messages(call_id: str):  
    try:  
        conversation_state = conversation_states[call_id]
        gpt_client = conversation_states[call_id]['gpt_client'] 

        # トランスクリプトのバッファを初期化
        if 'transcript_buffer' not in conversation_state:  
            conversation_state['transcript_buffer'] = ''  
        while not gpt_client.closed:  
            message = await gpt_client.recv()  
            if message:  
                if message.type == "response.audio.delta":  
                    # 音声データの delta を処理  
                    audio_data_base64 = message.delta  
                    audio_data = base64.b64decode(audio_data_base64)  
                    await receive_audio_for_outbound(call_id, audio_data)  
                elif message.type == "response.audio_transcript.delta":  
                    # テキストの delta を処理  
                    transcript_delta = message.delta  
                    print_debug(f"Received transcript delta for call_id {call_id}: {transcript_delta}", log_level="debug") 
                    
                    # バッファに delta を追加  
                    conversation_state['transcript_buffer'] += transcript_delta   
  
                    # デルタの内容をチェックして、文の終わりを検出  
                    if any(transcript_delta.endswith(punct) for punct in ['。', '！', '？', '.', '!', '?', '\n']):  
                        # 文末を検出したら、バッファの内容を処理  
                        complete_sentence = conversation_state['transcript_buffer'].strip()  
                        print_debug(f"Complete sentence for call_id {call_id}: {complete_sentence}")  

                        # バッファをリセット  
                        conversation_state['transcript_buffer'] = ''  
                elif message.type == "input.audio_transcript":  
                    # ユーザーの発話のトランスクリプトを取得  
                    user_transcript = message.text  
                    print_debug(f"User transcript for call_id {call_id}: {user_transcript}")   
                elif message.type == "response.audio":  
                    await receive_audio_for_outbound(call_id, message.data)  
                elif message.type == "response.text":  
                    # テキストレスポンスの処理（必要に応じて）  
                    print_debug(f"Received text response for call_id {call_id}: {message.text}")   
    except Exception as e:  
        print_debug(f"Exception in receive_messages for call_id {call_id}: {e}")  

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
            print_debug(f"No active websocket for call_id: {call_id}")  
    else:  
        print_debug(f"No conversation state for call_id: {call_id}") 

async def handle_job_offers(job_id: str):    
    while True:    
        try:    
            await asyncio.sleep(1)  
            for worker_id in ["worker-0", "worker-1", "worker-2", "worker-3", "worker-4","worker-5"]:    
                worker = await router_client.get_worker(worker_id=worker_id) 
                print_debug(f"Worker {worker_id} state: {worker.state}")
                print_debug(f"Worker {worker_id} available capacity: {worker.capacity}")
                print_debug(f"Worker {worker_id} offers: {worker.offers}", log_level = "debug") 
                print("job_id:", job_id)
                if worker and worker.offers:    
                    for offer in worker.offers: 
                        print("offer.job_id:", offer.job_id)   
                        if offer.job_id == job_id:  
                            print_debug(f"Worker {worker_id} has an active offer for job {offer.job_id}")  
                            accept = await router_client.accept_job_offer(worker_id=worker_id, offer_id=offer.offer_id)  
                            print_debug(f"Worker {worker_id} is assigned job {accept.job_id} with assignment ID {accept.assignment_id}")  
  
                            # job_idに関連するcall_idを取得  
                            call_id = job_id_to_call_id.get(job_id)  
                            if call_id:  
                                conversation_state = conversation_states.get(call_id)  
                                if conversation_state:  
                                    # ワーカーを会話状態に割り当てる  
                                    conversation_state['assigned_worker'] = worker  
                                    conversation_state['assignment_id'] = accept.assignment_id  
                                    print_debug(f"Assigned worker {worker_id} to call_id {call_id}")  

                                    if conversation_state.get('pending_job_completion'):  
                                        previous_job_id = conversation_state.get('job_id')  
                                        previous_assignment_id = accept.assignment_id  # 今回割り当てられた assignment_id を使用  
                                        await handle_job_completion(previous_job_id, previous_assignment_id)  
                                        conversation_state.pop('pending_job_completion', None)  
                                        # 会話状態から以前のジョブ情報を削除  
                                        conversation_state.pop('job_id', None)  
                                        conversation_state.pop('assignment_id', None) 

                                    # WebSocketが準備できていれば会話を開始  
                                    if conversation_state.get('websocket_ready'):  
                                        await start_conversation(call_id)  
                                else:  
                                    print_debug(f"Conversation state not found for call_id: {call_id}")  
                            else:  
                                print_debug(f"Call ID not found for job_id: {job_id}")  
 
                            return  # ジョブが割り当てられたらループを終了     
                else:    
                    print_debug(f"No offers for worker {worker_id}")    
        except Exception as e:    
            print_debug(f"Error in handle_job_offers: {e}")    

# Function to handle job completion
async def handle_job_completion(job_id: str, assignment_id: str):
    await router_client.complete_job(job_id=job_id, assignment_id=assignment_id)
    print_debug(f"Job {job_id} completed")
    await router_client.close_job(job_id=job_id, assignment_id=assignment_id, options=CloseJobOptions(disposition_code="Resolved"))
    print_debug(f"Job {job_id} closed")
    # ジョブがクローズされるまで待機  
    job_closed = False  
    while not job_closed:  
        job = await router_client.get_job(job_id=job_id)  
        if job.status == "closed":  
            job_closed = True  
        else:  
            await asyncio.sleep(0.5)  # 0.5秒待機して再度確認  
  
    await router_client.delete_job(job_id)  
    print_debug(f"Job {job_id} deleted")  

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
