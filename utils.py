import base64
from datetime import datetime

from azure.communication.callautomation import (
    CommunicationUserIdentifier,
    PhoneNumberIdentifier,
    MicrosoftTeamsUserIdentifier
)

# ログレベル設定（必要に応じて変更してください）
print_log_level = "info"  # Options: None, "info", "debug"
log_levels = {None: 0, "info": 1, "debug": 2}

def print_debug(*msg, log_level="info"):
    if log_levels.get(log_level, -1) <= log_levels.get(print_log_level, -1):
        print(*msg, flush=True)

def parse_communication_identifier(data):
    """
    発信者の CommunicationIdentifier をパースして返します。
    """
    kind = data.get("kind")
    if kind == "communicationUser":
        return CommunicationUserIdentifier(data.get("communicationUser", {}).get("id", data.get("rawId")))
    elif kind == "phoneNumber":
        return PhoneNumberIdentifier(data.get("phoneNumber", {}).get("value", data.get("rawId")))
    elif kind == "microsoftTeamsUser":
        teams_user = data.get("microsoftTeamsUser", {})
        return MicrosoftTeamsUserIdentifier(
            user_id=teams_user.get("userId", data.get("rawId")),
            is_anonymous=teams_user.get("isAnonymous", False),
            cloud=teams_user.get("cloud", "")
        )
    else:
        raise ValueError(f"Unsupported identifier type: {kind}")

def base64_encode_audio(data: bytes) -> str:
    """
    バイト列の音声データをBase64エンコードした文字列に変換します。
    """
    return base64.b64encode(data).decode("utf-8")

def base64_decode_audio(encoded_audio: str) -> bytes:
    """
    Base64エンコードされた音声データの文字列をバイト列に変換します。
    """
    return base64.b64decode(encoded_audio)

def get_utc_timestamp_z() -> str:
    """
    現在のUTCタイムスタンプを ISO 8601 形式（末尾に 'Z' を付与）で取得します。
    """
    return datetime.utcnow().isoformat() + "Z"
