import uuid
import asyncio
from models import ConversationState
from settings import settings
from call_context import CallContext
from azure.core.exceptions import ResourceNotFoundError
from azure.communication.jobrouter.aio import JobRouterClient, JobRouterAdministrationClient
from azure.communication.jobrouter.models import (
    DistributionPolicy,
    RouterQueue,
    RouterWorker,
    RouterWorkerSelector,
    LabelOperator,
    RouterJob,
    AcceptJobOfferResult,
    CloseJobOptions,
    LongestIdleMode,
    RouterChannel
)

class JobRouterBase:
    def __init__(self, connection_string: str) -> None:
        self._admin_client = JobRouterAdministrationClient.from_connection_string(connection_string)
        self._client = JobRouterClient.from_connection_string(connection_string)

    async def _upsert_distribution_policy(self, dist_policy: DistributionPolicy) -> DistributionPolicy:
        policy = await self._admin_client.upsert_distribution_policy(
            distribution_policy_id = dist_policy.id,
            offer_expires_after_seconds = dist_policy.offer_expires_after_seconds,
            mode = dist_policy.mode,
            name = dist_policy.name
        )
        return policy
    
    async def _upsert_queue(self, queue: RouterQueue) -> RouterQueue:
        queue = await self._admin_client.upsert_queue(
            queue_id = queue.id,
            name = queue.name,
            distribution_policy_id = queue.distribution_policy_id
        )
        return queue
    
    async def _upsert_worker(self, worker: RouterWorker) -> RouterWorker:
        worker = await self._client.upsert_worker(
            worker_id = worker.id,
            capacity = worker.capacity,
            queues = worker.queues,
            labels = worker.labels,
            channels = worker.channels,
            available_for_offers = True
        )
        return worker

    async def _upsert_job(self, job: RouterJob) -> RouterJob:
        job = await self._client.upsert_job(
            job_id = job.id,
            channel_id = job.channel_id,
            queue_id = job.queue_id,
            priority = job.priority,
            requested_worker_selectors = job.requested_worker_selectors
        )
        return job

    async def _accept_job_offer(self, worker: RouterWorker) -> AcceptJobOfferResult:
        job_offer = await self._client.accept_job_offer(
            worker_id = worker.id,
            offer_id = worker.offers[0].offer_id
        )
        return job_offer

    async def _complete_job(self, job: RouterJob) -> None:
        await self._client.close_job(
            job_id = job.id,
            assignment_id = job.assignments[0].assignment_id
        )
    
    async def _close_job(self, job: RouterJob) -> None:
        close_job_options = CloseJobOptions(
            disposition_code = "Resolved",
        )
        await self._client.close_job(
            job_id = job.id,
            assignment_id = job.assignments[0].assignment_id,
            close_job_options = close_job_options
        )

    async def _delete_job(self, job: RouterJob) -> None:
        await self._client.delete_job(
            job_id = job.id
        )


class JobRouter(JobRouterBase):
    def __init__(self) -> None:
        super().__init__(settings.ACS_CONNECTION_STRING)
        self._distribution_policy_id = settings.DISTRIBUTION_POLICY_ID
        self._distribution_name = settings.DISTRIBUTION_POLICY_NAME
        self._queue_id = settings.QUEUE_ID
        self._queue_name = settings.QUEUE_NAME
        self._worker_id = settings.WORKER_ID
        self._worker_capacity = settings.WORKER_CAPACITY
        self._worker_labels = settings.WORKER_LABELS
        self._channel_id = settings.CHANNEL_ID
        self._capacity_cost_per_job = settings.CAPACITY_COST_PER_JOB
    
    async def init(self) -> None:
        self._dist_policy = await self.create_distribution_policy_if_not_exists()
        self._queue = await self.create_queue_if_not_exists()
        self._worker = await self.create_worker()

    async def create_distribution_policy_if_not_exists(self) -> DistributionPolicy:
        try:
            # 分配ポリシーがすでに存在するか確認
            existing_policy = await self._admin_client.get_distribution_policy(distribution_policy_id = self._distribution_policy_id)
            print(f"Distribution policy '{self._distribution_policy_id}' already exists. Skipping creation.")
            return existing_policy
        except ResourceNotFoundError:
            # 存在しなければ作成
            print(f"Distribution policy '{self._distribution_policy_id}' not found. Creating...")
            policy = self._create_distribution_policy()
            return await self._upsert_distribution_policy(policy)
    
    def _create_distribution_policy(self) -> DistributionPolicy:
        return DistributionPolicy(
            id = self._distribution_policy_id,
            name = self._distribution_name,
            mode = LongestIdleMode(),
            offer_expires_after_seconds = 60
        )
    
    async def create_queue_if_not_exists(self) -> RouterQueue:
        try:
            # キューがすでに存在するか確認
            existing_queue = await self._admin_client.get_queue(queue_id = self._queue_id)
            print(f"Queue '{self._queue_id}' already exists. Skipping creation.")
            return existing_queue
        except ResourceNotFoundError:
            # 存在しなければ作成
            print(f"Queue '{self._queue_id}' not found. Creating...")
            queue = self._create_queue()
            return await self._upsert_queue(queue = queue)
        
    def _create_queue(self) -> RouterQueue:
        queue = RouterQueue(
            id = self._queue_id,
            name = self._queue_name,
            distribution_policy_id = self._distribution_policy_id
        )
        return queue
    
    async def create_worker(self) -> RouterWorker:
        try:
            # 既存ワーカーがいるか確認
            await self._client.get_worker(worker_id = self._worker_id)
            print(f"Worker '{self._worker_id}' already exists. Re-applying labels/channels.")
        except ResourceNotFoundError:
            print(f"Worker '{self._worker_id}' not found. Creating new one.")
            
        # ワーカーの作成
        fresh = self._create_worker()                   
        return await self._upsert_worker(worker = fresh)
    
    def _create_worker(self) -> RouterWorker:
        worker = RouterWorker(
            id = self._worker_id,
            capacity = self._worker_capacity,
            queues = [self._queue_id],
            labels = self._worker_labels,
            channels = self._create_channels(),
        )
        return worker

    def _create_channels(self) -> list:
        channels = [
            RouterChannel(
                channel_id=self._channel_id,
                capacity_cost_per_job=self._capacity_cost_per_job
            )
        ]
        return channels

    async def upsert_job(self, job_id: str) -> RouterJob:
        job = self._create_job(job_id)
        return await self._upsert_job(job = job)

    def _create_job(self, job_id: str) -> RouterJob:
        job = RouterJob(
            id = job_id,
            channel_id = self._channel_id,
            queue_id = self._queue_id,
            priority = 1,
            requested_worker_selectors = self._create_worker_selectors()
        )
        return job

    def _create_worker_selectors(self) -> list:
        worker_selectors = [
            RouterWorkerSelector(
                key = "Role",
                label_operator = LabelOperator.EQUAL,
                value = self._worker_labels["Role"]
            )
        ]
        return worker_selectors

    async def wait_job_offer(self, conversation_state: ConversationState) -> ConversationState:
        while True:
            try:
                # ワーカーの状態をポーリングしてオファーを受け入れる
                await asyncio.sleep(1)
                worker = await self._client.get_worker(worker_id = self._worker_id)
                print(f"Debug: Worker {worker.id} offers: {worker.offers}")
                print("Debug: self._worker_id", self._worker_id)
                print("Debug: conversation_state", conversation_state)
                if worker and worker.offers:
                    job_offer = await self._accept_job_offer(worker = worker)
                    print(f"Job offer accepted: {job_offer}")
                    conversation_state.job_assignment_id = job_offer.assignment_id
                    conversation_state.worker_id = worker.id
                    conversation_state.job_id = job_offer.job_id
                    print(f"Worker {worker.id} is assigned job {job_offer.job_id} with assignment ID {job_offer.assignment_id}")
                    break
            except Exception as e:
                print(f"Error accepting job offer: {e}")
                break
        return conversation_state

    async def finish_job(self, job: RouterJob) -> None:
        await self._complete_job(job = job)
        await self._close_job(job = job)
        await self._delete_job(job = job)
        print(f"Job {job.id} completed, closed and deleted.")

    async def finish_job_by_id(self, job_id: str) -> None:
        try:
            job = await self._client.get_job(job_id = job_id)
            await self.finish_job(job = job)
        except ResourceNotFoundError:
            print(f"Job {job_id} not found.")

    async def create_and_assign_job(self, call_context: CallContext) -> None:
        try:
            job = await self.upsert_job(str(uuid.uuid4()))
            print(f"Job created and upserted: {job.id}")
            print("Debug: job", job)
            await self.wait_job_offer(call_context.conversation_state)
            print(f"Debug: Job offer accepted: {call_context.conversation_state.job_assignment_id}")
        except Exception as e:
            print(f"Error creating and assigning job: {e}")
