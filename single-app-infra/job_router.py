import asyncio
from azure.communication.jobrouter.models import (
    LongestIdleMode,
    RouterWorkerSelector,
    LabelOperator,
    RouterChannel,
    CloseJobOptions,
)
from utils import print_debug
from clients import router_admin_client, router_client

async def init_job_router_state(app):
    """
    Initialize the Job Router state by creating a distribution policy, queues, and workers.
    """
    # Create a distribution policy
    distribution_policy = await router_admin_client.upsert_distribution_policy(
        distribution_policy_id="distribution-policy",
        offer_expires_after_seconds=60,
        mode=LongestIdleMode(),
        name="Distribution policy"
    )
    app.state.distribution_policy = distribution_policy

    # Define queue settings and create queues
    queues_settings = [
        {"id": "queue-0", "name": "QueueA"},
        {"id": "queue-1", "name": "QueueB"}
    ]
    app.state.queues = {}
    for queue in queues_settings:
        created_queue = await router_admin_client.upsert_queue(
            queue_id=queue["id"],
            name=queue["name"],
            distribution_policy_id=distribution_policy.id
        )
        app.state.queues[queue["id"]] = created_queue
        print_debug(f"Queue {queue['id']} created", log_level="debug")  

    # Define worker settings and create workers
    workers_settings = [
        {"id": "worker-0", "queue_id": "queue-0", "capacity": 10, "capacity_cost": 1, "role": "RoleDefault"},
        {"id": "worker-1", "queue_id": "queue-1", "capacity": 10, "capacity_cost": 2, "role": "RoleA"},
        {"id": "worker-2", "queue_id": "queue-1", "capacity": 10, "capacity_cost": 2, "role": "RoleB"},
        {"id": "worker-3", "queue_id": "queue-1", "capacity": 10, "capacity_cost": 2, "role": "RoleC"},
        {"id": "worker-4", "queue_id": "queue-1", "capacity": 10, "capacity_cost": 2, "role": "RoleD"},
        {"id": "worker-5", "queue_id": "queue-1", "capacity": 10, "capacity_cost": 1, "role": "RoleE"},
    ]
    app.state.workers = {}
    for worker in workers_settings:
        created_worker = await router_client.upsert_worker(
            worker_id=worker["id"],
            capacity=worker["capacity"],
            queues=[worker["queue_id"]],
            labels={"Role": worker["role"]},
            channels=[RouterChannel(
                channel_id="voice",
                capacity_cost_per_job=worker["capacity_cost"])
            ],
            available_for_offers=True
        )
        app.state.workers[worker["id"]] = created_worker
        print_debug(f"Worker {worker['id']} created with role {worker['role']}", log_level="debug")

async def submit_job_to_queue(job_id: str, channel_id: str, queue_id: str, priority: int, role_label: str):
    """
    Submit a job to the specified queue with given selectors.
    """
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
    print_debug("Job submitted:", job, log_level="debug")
    return job.id

async def handle_job_offers(job_id: str, call_id: str, conversation_state: dict):
    """
    Continuously poll workers to detect and accept the offer for the given job.
    """
    while True:
        try:
            await asyncio.sleep(1)
            for worker_id in ["worker-0", "worker-1", "worker-2", "worker-3", "worker-4", "worker-5"]:
                worker = await router_client.get_worker(worker_id=worker_id)
                print_debug(f"Worker {worker_id} state: {worker.state}")
                print_debug(f"Worker {worker_id} available capacity: {worker.capacity}")
                print_debug(f"Worker {worker_id} offers: {worker.offers}", log_level="debug")
                if worker and worker.offers:
                    for offer in worker.offers:
                        if offer.job_id == job_id:
                            print_debug(f"Worker {worker_id} has an active offer for job {offer.job_id}")
                            accept = await router_client.accept_job_offer(worker_id=worker_id, offer_id=offer.offer_id)
                            print_debug(f"Worker {worker_id} is assigned job {accept.job_id} with assignment ID {accept.assignment_id}")
                            conversation_state['assigned_worker'] = worker  
                            conversation_state['assignment_id'] = accept.assignment_id  
                            print_debug(f"Assigned worker {worker_id} to call_id {call_id}")
                            return # ジョブが割り当てられたらループを終了  
            print_debug(f"No offers found for job {job_id} in this polling cycle.", log_level="debug")
        except Exception as e:
            print_debug(f"Error in handle_job_offers: {e}")

async def handle_job_offer_event(event: dict, conversation_state: dict):
    """
    Process an event triggered when a job offer is issued.
    Extracts necessary details from the event and accepts the job offer.
    """
    try:
        data = event.get("data", {})
        worker_id = data.get("workerId")
        job_id = data.get("jobId")
        offer_id = data.get("offerId")
        
        if not (worker_id and job_id and offer_id):
            print_debug("Invalid event data: missing workerId, jobId, or offerId", log_level="error")
            return
        
        print_debug(f"Received job offer event for worker {worker_id} and job {job_id}", log_level="debug")
        accept = await router_client.accept_job_offer(worker_id=worker_id, offer_id=offer_id)
        print_debug(f"Worker {worker_id} accepted job {job_id} with assignment ID {accept.assignment_id}", log_level="debug")
        
        conversation_state['assigned_worker'] = worker_id
        conversation_state['assignment_id'] = accept.assignment_id
    except Exception as e:
        print_debug(f"Error handling job offer event: {e}", log_level="error")

async def handle_job_completion(job_id: str, assignment_id: str):
    """
    Complete, close, and finally delete a job.
    """
    await router_client.complete_job(job_id=job_id, assignment_id=assignment_id)
    print_debug(f"Job {job_id} completed")
    await router_client.close_job(
        job_id=job_id,
        assignment_id=assignment_id,
        options=CloseJobOptions(disposition_code="Resolved")
    )
    print_debug(f"Job {job_id} closed")
    
    # Wait for job status to become "closed" before deletion.
    job_closed = False
    while not job_closed:
        job = await router_client.get_job(job_id=job_id)
        if job.status == "closed":
            job_closed = True
        else:
            await asyncio.sleep(0.5)
    await router_client.delete_job(job_id)
    print_debug(f"Job {job_id} deleted")
