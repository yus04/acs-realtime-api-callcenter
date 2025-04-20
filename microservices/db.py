from typing import Any
from azure.cosmos import CosmosClient, CosmosDict

class CosmosDB:
    def __init__(self, connection_string: str, database_name: str, container_name: str) -> None:
        _client = CosmosClient.from_connection_string(connection_string)
        self._database = _client.get_database_client(database_name)
        self._container = _client.get_container_client(container_name)
    
    def get_item(self, item_id: str, partition_key: str) -> CosmosDict[str, Any]:
        return self._container.read_item(item = item_id, partition_key = partition_key)
    
    def upsert_item(self, item: dict) -> CosmosDict[str, Any]:
        self._container.upsert_item(item)
        return item
