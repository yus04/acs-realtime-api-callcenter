import asyncio
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from azure.eventgrid import EventGridEvent, SystemEventNames
from call_context import CallContext, CallContextFactory
from call_handler import CallHandler
from job_router import JobRouter
from dtmf import DTMFHandler
from fastapi import WebSocket as FastAPIWebSocket
from websocket import WebSocket as ACSWebSocket
from azure.eventgrid import EventGridEvent, SystemEventNames
from azure.core.messaging import CloudEvent

router = APIRouter()

@router.get("/")
async def read_root():
    print("Sample ACS Realtime API Call Center is running")
    return PlainTextResponse("Sample ACS Realtime API Call Center is running")

@router.post("/api/incomingCall")
async def incoming_call_handler(request: Request):
    print("Incoming call received")
    factory = CallContextFactory(request)
    call_context = await factory.build()
    job_router: JobRouter = request.app.state.job_router
    call_handler = CallHandler(call_context.call_id)

    for event_dict in call_context.events:
        event = EventGridEvent.from_dict(event_dict)

        # Event Grid Subscription 検証
        if event.event_type == SystemEventNames.EventGridSubscriptionValidationEventName:
            validation_code = event.data["validationCode"]
            return JSONResponse(content = {"validationResponse": validation_code})
        
        # incoming call event のハンドリング
        elif event.event_type == "Microsoft.Communication.IncomingCall":
            print("Incoming call event received")
            try:
                incoming_call_context = event.data.get("incomingCallContext")
                print("Debug: incoming_call_context", incoming_call_context)
                await job_router.create_and_assign_job(call_context)
                incoming_call_context = event.data.get("incomingCallContext")
                await call_handler.answer_call(incoming_call_context, call_context)
                return JSONResponse(content = {"message": "Call answeared"}, status_code = 200)
            except Exception as e:
                print(f"Error handling incoming call: {e}")
                return JSONResponse(content = {"message": "Error handling incoming call"}, status_code = 500)

@router.post("/api/callbacks/{call_id}")
async def handle_callback(request: Request, call_id: str):
    print("Callback event received")
    factory = CallContextFactory(request, call_id)
    call_context: CallContext = await factory.build()
    realtime = request.app.state.realtime_manager.get(call_id)
    job_router: JobRouter = request.app.state.job_router
    dtmf_handler = DTMFHandler(job_router, call_id, realtime)
    call_handler = CallHandler(call_id)

    for event_dict in call_context.events:
        event = CloudEvent.from_dict(event_dict)

        # 通話が開始された時
        if event.type == "Microsoft.Communication.CallConnected":
            print("Call connected")
            asyncio.create_task(dtmf_handler.start_recognition(call_context.conversation_state))

        # DTMFトーンの受信
        elif event.type == "Microsoft.Communication.ContinuousDtmfRecognitionToneReceived":
            print("DTMF tone received")
            tone = event.data.get("tone")
            if tone in DTMFHandler.AI_ROLE_MAP:
                await dtmf_handler.handle_tone_received(call_context, tone)
            elif tone in DTMFHandler.HUMAN_ROLE_MAP:
                print("transfering to human operator...")
                call_handler.transfer_call(call_context)
            else:
                print(f"Unhandled DTMF tone: {tone}")

        # その他のイベント
        elif event.type == "Microsoft.Communication.RouterJobQueued":
            print("Job queued")
        elif event.type == "Microsoft.Communication.RouterJobOffered":
            print("Job offered")
        elif event.type == "Microsoft.Communication.RouterWorkerOfferAccepted":
            print("Worker offer accepted")
        elif event.type == "Microsoft.Communication.MediaStreamingStarted":
            print("Media streaming started")
        elif event.type == "Microsoft.Communication.CallDisconnected":
            print("Call disconnected")
            await call_handler.hangup(call_context)
    return Response(status_code = 200)

@router.websocket("/ws/{call_id}")
async def websocket_endpoint(websocket: FastAPIWebSocket, call_id: str):
    print("WebSocket connection established")
    conversation_state = websocket.app.state.conversation_state_manager.get(call_id)
    ws = ACSWebSocket(websocket, call_id, None)
    realtime = websocket.app.state.realtime_manager.create(call_id, ws)
    ws._realtime = realtime
    await ws.websocket_handler(conversation_state)
