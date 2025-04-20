import uuid
from job_router import JobRouter
from call_context import CallContext
from azure.communication.callautomation import DtmfTone, PhoneNumberIdentifier, CallConnectionClient

class DTMFHandler:
    ROLE_MAP = {
        DtmfTone.ONE.value: "RoleA",
        DtmfTone.TWO.value: "RoleB",
        DtmfTone.THREE.value: "RoleC",
        DtmfTone.FOUR.value: "RoleD",
        DtmfTone.FIVE.value: "RoleE"
    }

    def __init__(self, job_router: JobRouter, call_id: str) -> None:
        self._call_id = call_id
        self._job_router = job_router
        self._operation_context = f"dtmf_{call_id}_{uuid.uuid4()}"

    async def start_recognition(self, call_connection: CallConnectionClient) -> None:
        try:
            await call_connection.start_continuous_dtmf_recognition(
                target_participant = PhoneNumberIdentifier(self._call_id),
                operation_context = self._operation_context,
            )
            print(f"DTMF recognition started for call_id {self._call_id} with operation_context {self._operation_context}.")
        except Exception as e:
            print(f"Error starting DTMF recognition for call_id {self._call_id}: {e}")

    async def handle_tone_received(self, call_context: CallContext, tone: str) -> None:
        conversation_state = call_context.conversation_state
        # ロールの変更
        self._switch_role(conversation_state, tone)
        # 旧ジョブの完了
        self._finish_previous_job(conversation_state)
        # 新しいジョブを作成・キューに投入
        self._job_router.create_and_assign_job(call_context)

    def _switch_role(self, call_context: CallContext, tone: str) -> None:
        if tone in self.ROLE_MAP:
            new_role = self.ROLE_MAP[tone]
            print(f"Switching role to {new_role}")
            call_context.conversation_state.current_role = new_role
        else:
            print(f"Unhandled DTMF tone: {tone}")
    
    def _finish_previous_job(self, call_context: CallContext) -> None:
        previous_job_id = call_context.conversation_state.job_id

        if previous_job_id:
            self._job_router.finish_job_by_id(previous_job_id)
        
        call_context.conversation_state.job_id = None
        call_context.conversation_state.job_assignment_id = None
