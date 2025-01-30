import os  
import asyncio  
from dotenv import load_dotenv  
from azure.communication.jobrouter.aio import JobRouterClient  
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError  
  
async def main():  
    # 環境変数の読み込み  
    load_dotenv()  
  
    # Azure Communication Services の接続文字列を取得  
    ACS_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING")  
  
    if not ACS_CONNECTION_STRING:  
        print("ACS_CONNECTION_STRING 環境変数を設定してください。")  
        return  
  
    # JobRouter クライアントの初期化  
    router_client = JobRouterClient.from_connection_string(ACS_CONNECTION_STRING)  
  
    try:  
        # ジョブのクリーンアップ  
        print("ジョブをクリーンアップしています...")  
        async for job in router_client.list_jobs():  
            try:  
                # ジョブのキャンセルと削除  
                await router_client.cancel_job(job_id=job.id)  
                print(f"キャンセルされたジョブ: {job.id}")  
  
                if job.assignments:  
                    for assignment_id in job.assignments.keys():  
                        await router_client.close_job(  
                            job_id=job.id,  
                            assignment_id=assignment_id,  
                            disposition_code="Cancelled"  
                        )  
                        print(f"クローズされたジョブ: {job.id}（アサインメントID: {assignment_id}）")  
                else:  
                    print(f"ジョブ {job.id} にアサインメントがありません。")  
  
                await router_client.delete_job(job.id)  
                print(f"削除されたジョブ: {job.id}")  
  
            except ResourceNotFoundError:  
                print(f"ジョブが見つかりませんでした: {job.id}")  
            except HttpResponseError as e:  
                print(f"ジョブの処理中にエラーが発生しました {job.id}: {e}")  
            except Exception as e:  
                print(f"予期せぬエラーが発生しました {job.id}: {e}")  
  
        # ワーカーのクリーンアップ  
        print("ワーカーをクリーンアップしています...")  
        async for worker_item in router_client.list_workers():  
            try:  
                # ワーカーの詳細情報を取得  
                worker = await router_client.get_worker(worker_id=worker_item.id)  
  
                # ワーカーを更新  
                await router_client.upsert_worker(  
                    worker_id=worker.id,  
                    labels=worker.labels,  
                    tags=worker.tags,  
                    available_for_offers=True,  
                    capacity=10 
                )  
                print(f"リセットされたワーカー: {worker.id}")  
  
            except ResourceNotFoundError:  
                print(f"ワーカーが見つかりませんでした: {worker_item.id}")  
            except HttpResponseError as e:  
                print(f"ワーカーの更新中にエラーが発生しました {worker_item.id}: {e}")  
            except Exception as e:  
                print(f"予期せぬエラーが発生しました {worker_item.id}: {e}")  
  
    finally:  
        # クライアントセッションを閉じる  
        await router_client.close()  
  
if __name__ == "__main__":  
    asyncio.run(main())  
