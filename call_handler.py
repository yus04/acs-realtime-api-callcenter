import asyncio
import uuid
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from azure.eventgrid import EventGridEvent, SystemEventNames
from azure.core.messaging import CloudEvent
from azure.communication.callautomation import (
    MediaStreamingOptions,
    AudioFormat,
    MediaStreamingTransportType,
    MediaStreamingContentType,
    MediaStreamingAudioChannelType,
    DtmfTone,
)

from config import CALLBACK_EVENTS_URI
from clients import acs_client
from job_router import submit_job_to_queue, handle_job_offers, handle_job_completion
from conversation_manager import update_conversation
from utils import print_debug, parse_communication_identifier

router = APIRouter()

@router.get("/")
async def read_root():
    print_debug("Sample ACS Realtime API Call Center is running")
    return PlainTextResponse("Sample ACS Realtime API Call Center is running")

@router.post("/api/incomingCall")
async def incoming_call_handler(request: Request):
    print_debug("Incoming call received")
    events = await request.json()
    print_debug("events:", events, log_level="debug")
    for event_dict in events:
        event = EventGridEvent.from_dict(event_dict)
        print_debug("event:", event, log_level="debug")
        if event.event_type == SystemEventNames.EventGridSubscriptionValidationEventName:
            validation_code = event.data["validationCode"]
            print_debug("Validation code:", validation_code)
            return JSONResponse(content={"validationResponse": validation_code})
        elif event.event_type == "Microsoft.Communication.IncomingCall":
            call_id = str(uuid.uuid4())
            caller_id = (
                event.data["from"]["phoneNumber"]["value"]
                if event.data["from"]["kind"] == "phoneNumber"
                else event.data["from"]["rawId"]
            )
            incoming_call_context = event.data["incomingCallContext"]
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
                enable_bidirectional=True,
                audio_format=AudioFormat.PCM24_K_MONO,
            )

            # Answer the incoming call
            await acs_client.answer_call(
                incoming_call_context=incoming_call_context,
                operation_context="incomingCall",
                callback_url=callback_uri,
                media_streaming=media_streaming_options,
            )

            selected_role = "RoleDefault"
            generated_job_id = str(uuid.uuid4())
            # Assuming a queue has already been created and attached to the FastAPI app state
            submitted_job_id = await submit_job_to_queue(
                generated_job_id, "voice", request.app.state.queue.id, priority=1, role_label=selected_role
            )

            request.app.state.job_id_to_call_id[submitted_job_id] = call_id
            print_debug("Call ID", call_id)

            caller = parse_communication_identifier(event.data["from"])
            conversation_state = {
                "call_id": call_id,
                "job_id": submitted_job_id,
                "caller_id": caller_id,
                "caller_communication_identifier": caller,
                "media_streaming_options": media_streaming_options,
                "websocket_ready": False,
                "current_role": None,
            }

            request.app.state.conversation_states[call_id] = conversation_state
            # conversation_state = request.app.state.conversation_states[call_id]
            print_debug("Conversation states:", conversation_state)

            # Start processing job offers asynchronously
            if not conversation_state.get("job_offer_task"):
                conversation_state["job_offer_task"] = asyncio.create_task(
                    handle_job_offers(submitted_job_id, call_id, conversation_state)
            )
            return Response(status_code=200)
    return Response(status_code=400)

@router.post("/api/callbacks/{call_id}")
async def handle_callback(call_id: str, request: Request):
    events = await request.json()
    print_debug("Callback events:", events, log_level="debug")
    for event_dict in events:
        event = CloudEvent.from_dict(event_dict)
        print_debug("Callback event:", event, log_level="debug")
        call_connection_id = event.data["callConnectionId"]
        conversation_state = request.app.state.conversation_states.get(call_id)
        
        if event.type == "Microsoft.Communication.CallConnected":
            print_debug("Call connected")
            await start_dtmf_recognition(call_connection_id, call_id, conversation_state)
        elif event.type == "Microsoft.Communication.ContinuousDtmfRecognitionToneReceived":
            tone = event.data["tone"]
            role_map = {
                DtmfTone.ONE.value: "RoleA",
                DtmfTone.TWO.value: "RoleB",
                DtmfTone.THREE.value: "RoleC",
                DtmfTone.FOUR.value: "RoleD",
                DtmfTone.FIVE.value: "RoleE"
            }
            if tone in role_map:
                print_debug(f"Tone {tone} received, switching role to {role_map[tone]}")
                conversation_state["current_role"] = role_map[tone]
            else:
                print_debug(f"Received unhandled DTMF tone: {tone}")

            previous_job_id = conversation_state.get("job_id")
            previous_assignment_id = conversation_state.get("assignment_id")
            # Handle previous job completion if necessary
            if previous_job_id:
                if previous_assignment_id:
                    await handle_job_completion(previous_job_id, previous_assignment_id)
                    print_debug(f"Completed previous job {previous_job_id}.")
                else:
                    print_debug("No assignment ID found for previous job, skipping job completion.")
                conversation_state.pop("job_id", None)
                conversation_state.pop("assignment_id", None)
                removed_call_id = request.app.state.job_id_to_call_id.pop(previous_job_id, None)
                if removed_call_id is not None:
                    print_debug(f"Removed job_id {removed_call_id} with call_id {removed_call_id}")
                else:
                    print_debug(f"Job_id {removed_call_id} not found in mapping")

            new_job_id = str(uuid.uuid4())
            conversation_state["job_id"] = new_job_id
            submitted_job_id = await submit_job_to_queue(
                new_job_id,
                "voice",
                request.app.state.queue.id,
                priority=1,
                role_label=conversation_state["current_role"],
            )
            request.app.state.job_id_to_call_id[new_job_id] = call_id
            print_debug("Job ID to call ID mapping:", request.app.state.job_id_to_call_id)
            # asyncio.create_task(handle_job_offers(submitted_job_id, call_id, conversation_state))
            if not conversation_state.get("job_offer_task"):
                conversation_state["job_offer_task"].cancel()
            conversation_state["job_offer_task"] = asyncio.create_task(
                handle_job_offers(submitted_job_id, call_id, conversation_state)
            )
            await update_conversation(call_id, conversation_state)
        elif event.type == "Microsoft.Communication.RecognizeCompleted":
            print_debug("Recognize completed")
        elif event.type == "Microsoft.Communication.MediaStreamingStarted":
            print_debug("Media streaming started")
        elif event.type == "Microsoft.Communication.CallDisconnected":
            print_debug("Call disconnected")
            await handle_hangup(call_connection_id)
    return Response(status_code=200)

async def start_dtmf_recognition(call_connection_id: str, call_id: str, conversation_state: dict):
    print_debug(f"Starting DTMF recognition for call_id {call_id}")
    if not conversation_state:
        print_debug(f"No conversation state found for call_id {call_id}")
        return
    if conversation_state.get("dtmf_recognition_in_progress", False):
        print_debug(f"DTMF recognition already in progress for call_id {call_id}")
        return
    conversation_state["dtmf_recognition_in_progress"] = True
    call_connection = acs_client.get_call_connection(call_connection_id)
    target_participant = conversation_state["caller_communication_identifier"]
    operation_context = f"dtmf_{call_id}_{uuid.uuid4()}"
    try:
        await call_connection.start_continuous_dtmf_recognition(
            target_participant=target_participant,
            operation_context="dtmf-reco-on-c2",
        )
        print_debug(f"DTMF recognition started for call_id {call_id} with operation_context {operation_context}.")
    except Exception as e:
        print_debug(f"Error starting DTMF recognition for call_id {call_id}: {e}")
        conversation_state["dtmf_recognition_in_progress"] = False

async def handle_hangup(call_connection_id: str):
    try:
        await acs_client.get_call_connection(call_connection_id).hang_up(is_for_everyone=True)
    except Exception as e:
        print_debug(f"Error during hangup for connection {call_connection_id}: {e}")
