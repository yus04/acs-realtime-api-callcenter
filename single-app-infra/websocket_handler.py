from fastapi import WebSocket
from utils import print_debug
from conversation_manager import process_websocket_message_async, start_conversation

async def websocket_endpoint(websocket: WebSocket, call_id: str):
    print_debug("WebSocket connection established")
    await websocket.accept()

    # FastAPI アプリで共有されるグローバル状態から conversation_states を取得
    conversation_states = websocket.app.state.conversation_states
    conversation_state = conversation_states.get(call_id)
    if conversation_state is None:
        conversation_state = {
            'websocket': websocket,
            'gpt_client': None,
            'websocket_ready': True
        }
        conversation_states[call_id] = conversation_state
    else:
        conversation_state['websocket'] = websocket
        conversation_state['websocket_ready'] = True

    print_debug("conversation_state:", conversation_state)

    # 会話開始 (GPT クライアントとの接続を確立)
    await start_conversation(call_id, conversation_state)

    # ACS からのメッセージを待機
    try:
        while True:
            message = await websocket.receive()
            msg_type = message.get('type')
            if msg_type == 'websocket.receive':
                if 'text' in message:
                    text_data = message['text']
                    await process_websocket_message_async(call_id, text_data, conversation_state)
                elif 'bytes' in message:
                    data = message['bytes']
                    # 必要に応じてバイナリデータの処理を実装
            elif msg_type == 'websocket.disconnect':
                print_debug("WebSocket disconnected")
                break
    except Exception as e:
        print_debug(f"Exception in websocket_endpoint: {e}")
    finally:
        if conversation_state.get('gpt_client'):
            await conversation_state['gpt_client'].close()
            conversation_state['gpt_client'] = None
        conversation_states.pop(call_id, None)
        print_debug(f"Connection closed for call_id: {call_id}")
