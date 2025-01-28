# ACS Realtime API Call Center

## Setup

1. Clone the repository:
    ```bash
    git clone <repository_url>
    cd acs-realtime-api-callcenter
    ```

2. Create a virtual environment and activate it:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3. Install the required packages:
    ```bash
    pip install -r requirements.txt
    ```

4. Set up environment variables:
    ```.env
    ACS_CONNECTION_STRING="endpoint=https://xxxxxxxxxx.xxx.communication.azure.com/;accesskey=xxxxxxxxxxxxxxxxxxxxxxxx"
    CALLBACK_URI_HOST="https://xxxxxxxx-xxxx.asse.devtunnels.ms"
    AZURE_OPENAI_SERVICE_ENDPOINT="wss://xxxxxxxxxx.openai.azure.com/"
    AZURE_OPENAI_SERVICE_KEY="xxxxxxxxxxxxxxxxx"
    AZURE_OPENAI_DEPLOYMENT_NAME="xxxxxxxxxxxx"
    WEBSOCKET_HOST="xxxxxxxx-xxxx.asse.devtunnels.ms"
    ```

## Run the application

1. Start the FastAPI application:
    ```bash
    uvicorn main:app --host 0.0.0.0 --port 8080
    ```

2. The application will be available at `http://localhost:8080`.

## Usage

- The application will handle incoming calls, stream audio data, and interact with Azure OpenAI Service.
- WebSocket connections will be used to stream audio data between ACS and the application.
- Calls can be transferred to another worker or human operator as needed.