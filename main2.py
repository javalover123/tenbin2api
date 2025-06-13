import json
import os
import time
import uuid
import threading
from typing import Any, Dict, List, Optional, TypedDict, Union

import requests
import websocket
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from getCaptcha import getCaptcha, getTaskId


# Tenbin Account Management
class TenbinAccount(TypedDict):
    session_id: str
    is_valid: bool
    last_used: float
    error_count: int


# Global variables
VALID_CLIENT_KEYS: set = set()
TENBIN_ACCOUNTS: List[TenbinAccount] = []
TENBIN_MODELS: Dict[str, str] = {}  # 模型映射表，key 是模型名称，value 是内部模型 ID
account_rotation_lock = threading.Lock()
MAX_ERROR_COUNT = 3
ERROR_COOLDOWN = 300  # 5 minutes cooldown for accounts with errors
DEBUG_MODE = os.environ.get("DEBUG_MODE", "false").lower() == "true"
REQUEST_TIMEOUT = 120.0  # 请求超时时间，秒


# Pydantic Models
class ChatMessage(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]
    reasoning_content: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    stream: bool = True
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    raw_response: bool = False  # 是否返回原始响应


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "tenbin"


class ModelList(BaseModel):
    object: str = "list"
    data: List[ModelInfo]


class ChatCompletionChoice(BaseModel):
    message: ChatMessage
    index: int = 0
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChatCompletionChoice]
    usage: Dict[str, int] = Field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    )


class StreamChoice(BaseModel):
    delta: Dict[str, Any] = Field(default_factory=dict)
    index: int = 0
    finish_reason: Optional[str] = None


class StreamResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex}")
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[StreamChoice]


# FastAPI App
app = FastAPI(title="Tenbin OpenAI API Adapter")
security = HTTPBearer(auto_error=False)


def log_debug(message: str):
    """Debug日志函数"""
    if DEBUG_MODE:
        print(f"[DEBUG] {message}")


def load_client_api_keys():
    """Load client API keys from client_api_keys.json"""
    global VALID_CLIENT_KEYS
    try:
        with open("client_api_keys.json", "r", encoding="utf-8") as f:
            keys = json.load(f)
            VALID_CLIENT_KEYS = set(keys) if isinstance(keys, list) else set()
            print(f"Successfully loaded {len(VALID_CLIENT_KEYS)} client API keys.")
    except FileNotFoundError:
        print("Error: client_api_keys.json not found. Client authentication will fail.")
        VALID_CLIENT_KEYS = set()
    except Exception as e:
        print(f"Error loading client_api_keys.json: {e}")
        VALID_CLIENT_KEYS = set()


def load_tenbin_accounts():
    """Load Tenbin accounts from tenbin.json"""
    global TENBIN_ACCOUNTS
    TENBIN_ACCOUNTS = []
    try:
        with open("tenbin.json", "r", encoding="utf-8") as f:
            accounts = json.load(f)
            if not isinstance(accounts, list):
                print("Warning: tenbin.json should contain a list of account objects.")
                return

            for acc in accounts:
                session_id = acc.get("session_id")
                if session_id:
                    TENBIN_ACCOUNTS.append({
                        "session_id": session_id,
                        "is_valid": True,
                        "last_used": 0,
                        "error_count": 0
                    })
            print(f"Successfully loaded {len(TENBIN_ACCOUNTS)} Tenbin accounts.")
    except FileNotFoundError:
        print("Error: tenbin.json not found. API calls will fail.")
    except Exception as e:
        print(f"Error loading tenbin.json: {e}")


def load_tenbin_models():
    """Load Tenbin models from models.json"""
    global TENBIN_MODELS
    try:
        with open("models.json", "r", encoding="utf-8") as f:
            models_data = json.load(f)
            if isinstance(models_data, dict):
                TENBIN_MODELS = models_data
                print(f"Successfully loaded {len(TENBIN_MODELS)} models.")
            else:
                print("Warning: models.json should contain a dictionary of model mappings.")
                TENBIN_MODELS = {}
    except FileNotFoundError:
        print("Error: models.json not found. Model list will be empty.")
        TENBIN_MODELS = {}
    except Exception as e:
        print(f"Error loading models.json: {e}")
        TENBIN_MODELS = {}


def get_best_tenbin_account() -> Optional[TenbinAccount]:
    """Get the best available Tenbin account using a smart selection algorithm."""
    with account_rotation_lock:
        now = time.time()
        valid_accounts = [
            acc for acc in TENBIN_ACCOUNTS 
            if acc["is_valid"] and (
                acc["error_count"] < MAX_ERROR_COUNT or 
                now - acc["last_used"] > ERROR_COOLDOWN
            )
        ]
        
        if not valid_accounts:
            return None
            
        # Reset error count for accounts that have been in cooldown
        for acc in valid_accounts:
            if acc["error_count"] >= MAX_ERROR_COUNT and now - acc["last_used"] > ERROR_COOLDOWN:
                acc["error_count"] = 0
                
        # Sort by last used (oldest first) and error count (lowest first)
        valid_accounts.sort(key=lambda x: (x["last_used"], x["error_count"]))
        account = valid_accounts[0]
        account["last_used"] = now
        return account


def build_tenbin_prompt(messages: List[ChatMessage]) -> str:
    """将 OpenAI 格式的消息列表转换为 Tenbin 格式的单个字符串"""
    prompt = ""
    for msg in messages:
        role = msg.role
        content = msg.content
        if isinstance(content, list):
            # 简单处理多模态内容，只提取文本部分
            content = " ".join([
                item.get("text", "") 
                for item in content 
                if item.get("type") == "text"
            ])
        
        # 添加到提示中
        if role == "system":
            # 系统消息作为 Human 消息的前缀
            prompt += f"\n\nHuman: <system>{content}</system>"
        elif role == "user":
            prompt += f"\n\nHuman: {content}"
        elif role == "assistant":
            prompt += f"\n\nAssistant: {content}"
        # 忽略其他角色
    
    # 添加最后的 "Assistant:" 提示
    prompt += "\n\nAssistant:"
    return prompt


async def authenticate_client(
    auth: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    """Authenticate client based on API key in Authorization header"""
    if not VALID_CLIENT_KEYS:
        raise HTTPException(
            status_code=503,
            detail="Service unavailable: Client API keys not configured on server.",
        )

    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=401,
            detail="API key required in Authorization header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if auth.credentials not in VALID_CLIENT_KEYS:
        raise HTTPException(status_code=403, detail="Invalid client API key.")


@app.on_event("startup")
async def startup():
    """应用启动时初始化配置"""
    print("Starting Tenbin OpenAI API Adapter server...")
    load_client_api_keys()
    load_tenbin_accounts()
    load_tenbin_models()
    print("Server initialization completed.")


def get_models_list_response() -> ModelList:
    """Helper to construct ModelList response from cached models."""
    model_infos = [
        ModelInfo(
            id=model_id,
            created=int(time.time()),
            owned_by="tenbin"
        )
        for model_id in TENBIN_MODELS.keys()
    ]
    return ModelList(data=model_infos)


@app.get("/v1/models", response_model=ModelList)
async def list_v1_models(_: None = Depends(authenticate_client)):
    """List available models - authenticated"""
    return get_models_list_response()


@app.get("/models", response_model=ModelList)
async def list_models_no_auth():
    """List available models without authentication - for client compatibility"""
    return get_models_list_response()


@app.get("/debug")
async def toggle_debug(enable: bool = Query(None)):
    """切换调试模式"""
    global DEBUG_MODE
    if enable is not None:
        DEBUG_MODE = enable
    return {"debug_mode": DEBUG_MODE}


@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest, _: None = Depends(authenticate_client)
):
    """创建聊天完成 - 使用 Tenbin API"""
    # 检查模型是否存在
    if request.model not in TENBIN_MODELS:
        raise HTTPException(status_code=404, detail=f"Model '{request.model}' not found.")

    # 获取内部模型 ID
    internal_model_id = TENBIN_MODELS[request.model]
    
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided in the request.")
    
    log_debug(f"Processing request for model: {request.model} (internal ID: {internal_model_id})")
    
    # 构建 Tenbin 格式的提示
    prompt = build_tenbin_prompt(request.messages)
    log_debug(f"Built prompt with length: {len(prompt)}")
    
    # 尝试所有账户
    for attempt in range(len(TENBIN_ACCOUNTS)):
        account = get_best_tenbin_account()
        if not account:
            raise HTTPException(
                status_code=503, 
                detail="No valid Tenbin accounts available."
            )

        session_id = account["session_id"]
        log_debug(f"Using account with session_id ending in ...{session_id[-4:]}")
        
        try:
            # 获取执行令牌
            execution_token = get_tenbin_execution_token(internal_model_id, session_id)
            
            if request.stream:
                log_debug("Returning stream response")
                return StreamingResponse(
                    tenbin_stream_generator(request.model, prompt, session_id, execution_token),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )
            else:
                log_debug("Building non-stream response")
                return build_tenbin_non_stream_response(request.model, prompt, session_id, execution_token)

        except Exception as e:
            error_detail = str(e)
            log_debug(f"Tenbin API error: {error_detail}")

            with account_rotation_lock:
                # 增加错误计数
                account["error_count"] += 1
                log_debug(f"Account ...{session_id[-4:]} error count: {account['error_count']}")
                
                # 如果错误看起来是认证问题，标记账户为无效
                if "authentication" in error_detail.lower() or "unauthorized" in error_detail.lower():
                    account["is_valid"] = False
                    log_debug(f"Account ...{session_id[-4:]} marked as invalid due to auth error.")

    # 所有尝试都失败
    if request.stream:
        return StreamingResponse(
            error_stream_generator("All attempts to contact Tenbin API failed.", 503),
            media_type="text/event-stream",
            status_code=503,
        )
    else:
        raise HTTPException(status_code=503, detail="All attempts to contact Tenbin API failed.")


def get_tenbin_execution_token(model: str, session_id: str) -> str:
    """获取 Tenbin 执行令牌"""
    try:
        task_id = getTaskId()
        captcha = getCaptcha(task_id)
        url = "https://graphql.tenbin.ai/graphql"

        payload = {
            "operationName": "IssueExecutionTokensMultiple",
            "variables": {
                "turnstileToken": captcha,
                "models": [model],
            },
            "query": "query IssueExecutionTokensMultiple($turnstileToken: String!, $models: [ChatModel!]!) {\n  executionTokens: issueExecutionTokensMultiple(\n    turnstileToken: $turnstileToken\n    models: $models\n  )\n}",
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Content-Type": "application/json",
            "Cookie": f"sessionId={session_id}",
        }

        log_debug(f"Getting execution token for model: {model}")
        response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        
        execution_token = response.json()["data"]["executionTokens"][0]
        log_debug(f"Got execution token: {execution_token[:10]}...")
        return execution_token
    except Exception as e:
        log_debug(f"Error getting execution token: {e}")
        raise


def tenbin_stream_generator(model: str, prompt: str, session_id: str, execution_token: str):
    """Tenbin WebSocket 流式响应生成器"""
    stream_id = f"chatcmpl-{uuid.uuid4().hex}"
    created_time = int(time.time())
    
    # 发送初始角色增量
    yield f"data: {StreamResponse(id=stream_id, created=created_time, model=model, choices=[StreamChoice(delta={'role': 'assistant'})]).json()}\n\n"
    
    # 连接 WebSocket
    url = "wss://graphql.tenbin.ai/graphql"
    headers = {
        "Host": "graphql.tenbin.ai",
        "Connection": "Upgrade",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0",
        "Upgrade": "websocket",
        "Origin": "https://tenbin.ai",
        "Sec-WebSocket-Version": "13",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Cookie": f"sessionId={session_id}",
        "Sec-WebSocket-Key": "I/tTy5psJkboWYQfCypjVA==",
        "Sec-WebSocket-Extensions": "permessage-deflate; client_max_window_bits",
        "Sec-WebSocket-Protocol": "graphql-transport-ws",
    }
    
    ws = None
    try:
        log_debug("Connecting to WebSocket...")
        ws = websocket.create_connection(url, header=headers)
        ws.send(json.dumps({"type": "connection_init"}))
        init_response = ws.recv()
        log_debug(f"WebSocket init response: {init_response}")
        
        # 发送订阅请求
        payload = {
            "id": str(uuid.uuid4()),
            "type": "subscribe",
            "payload": {
                "variables": {
                    "prompt": prompt,
                    "executionToken": execution_token,
                    "stateToken": "",
                },
                "extensions": {},
                "operationName": "StartConversation",
                "query": "subscription StartConversation($executionToken: String!, $itemId: String, $itemDraftId: String, $systemPrompt: String, $prompt: String, $stateToken: String, $variables: [ConversationVariableInput!], $itemCallOption: ItemCallOption, $fileKey: String, $fileUploadIds: [String!], $selectedToolsByUser: [ToolType!]) {\n  startConversation(\n    executionToken: $executionToken\n    itemId: $itemId\n    itemDraftId: $itemDraftId\n    systemPrompt: $systemPrompt\n    prompt: $prompt\n    stateToken: $stateToken\n    variables: $variables\n    itemCallOption: $itemCallOption\n    fileKey: $fileKey\n    fileUploadIds: $fileUploadIds\n    selectedToolsByUser: $selectedToolsByUser\n  ) {\n    ...DeltaConversation\n    __typename\n  }\n}\n\nfragment DeltaConversation on AIConversationStreamResult {\n  seq\n  deltaToken\n  isFinished\n  newStateToken\n  error\n  fileUploadIds\n  toolResult {\n    id\n    title\n    url\n    faviconUrl\n    summary\n    __typename\n  }\n  action\n  activity\n  toolError\n  __typename\n}",
            },
        }
        
        log_debug("Sending subscription request...")
        ws.send(json.dumps(payload))
        
        # 处理响应
        accumulated_thinking = ""
        thinking_mode = False
        thinking_separator = "\n\n---\n\n"
        is_thinking_model = model == "Claude-3.7-Sonnet-Extended"
        
        while True:
            try:
                msg = ws.recv()
                log_debug(f"Received message: {msg[:100]}..." if len(msg) > 100 else msg)
                
                if msg.endswith('"type":"complete"}'):
                    log_debug("Received complete message")
                    break
                
                try:
                    data = json.loads(msg)
                    if data.get("type") != "next":
                        continue
                    
                    payload_data = data.get("payload", {}).get("data", {})
                    conversation = payload_data.get("startConversation", {})
                    
                    delta_token = conversation.get("deltaToken", "")
                    is_finished = conversation.get("isFinished", False)
                    
                    if delta_token:
                        if is_thinking_model:
                            # 检查是否包含思考/回答分隔符
                            if thinking_separator in accumulated_thinking + delta_token:
                                # 找到分隔符，切换到回答模式
                                if not thinking_mode:
                                    # 如果之前没有发送过思考内容，先发送累积的思考内容
                                    parts = (accumulated_thinking + delta_token).split(thinking_separator, 1)
                                    thinking_content = parts[0]
                                    answer_content = parts[1] if len(parts) > 1 else ""
                                    
                                    if thinking_content:
                                        yield f"data: {StreamResponse(id=stream_id, created=created_time, model=model, choices=[StreamChoice(delta={'reasoning_content': thinking_content})]).json()}\n\n"
                                    
                                    if answer_content:
                                        yield f"data: {StreamResponse(id=stream_id, created=created_time, model=model, choices=[StreamChoice(delta={'content': answer_content})]).json()}\n\n"
                                    
                                    thinking_mode = True
                                    accumulated_thinking = ""
                                else:
                                    # 已经在回答模式，直接发送内容
                                    yield f"data: {StreamResponse(id=stream_id, created=created_time, model=model, choices=[StreamChoice(delta={'content': delta_token})]).json()}\n\n"
                            else:
                                # 没有找到分隔符
                                if thinking_mode:
                                    # 已经在回答模式，直接发送内容
                                    yield f"data: {StreamResponse(id=stream_id, created=created_time, model=model, choices=[StreamChoice(delta={'content': delta_token})]).json()}\n\n"
                                else:
                                    # 继续累积思考内容
                                    accumulated_thinking += delta_token
                        else:
                            # 非思考模型，直接发送内容
                            yield f"data: {StreamResponse(id=stream_id, created=created_time, model=model, choices=[StreamChoice(delta={'content': delta_token})]).json()}\n\n"
                    
                    if is_finished:
                        # 如果还有未发送的思考内容，发送它
                        if is_thinking_model and not thinking_mode and accumulated_thinking:
                            yield f"data: {StreamResponse(id=stream_id, created=created_time, model=model, choices=[StreamChoice(delta={'reasoning_content': accumulated_thinking})]).json()}\n\n"
                        
                        # 发送完成信号
                        log_debug("Stream finished")
                        yield f"data: {StreamResponse(id=stream_id, created=created_time, model=model, choices=[StreamChoice(delta={}, finish_reason='stop')]).json()}\n\n"
                        yield "data: [DONE]\n\n"
                        break
                        
                except json.JSONDecodeError as e:
                    log_debug(f"JSON decode error: {e}")
                    continue
                    
            except websocket.WebSocketConnectionClosedException:
                log_debug("WebSocket connection closed")
                break
                
            except Exception as e:
                log_debug(f"Error processing message: {e}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                break
    
    except Exception as e:
        log_debug(f"WebSocket error: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"
    
    finally:
        if ws:
            try:
                ws.close()
                log_debug("WebSocket connection closed")
            except:
                pass


def build_tenbin_non_stream_response(model: str, prompt: str, session_id: str, execution_token: str) -> ChatCompletionResponse:
    """构建非流式响应"""
    full_content = ""
    full_reasoning_content = None
    
    # 使用流式生成器，但累积所有内容
    for chunk in tenbin_stream_generator(model, prompt, session_id, execution_token):
        if not chunk.startswith("data: ") or chunk.strip() == "data: [DONE]":
            continue
            
        try:
            data = json.loads(chunk[6:])  # 去掉 "data: " 前缀
            if "choices" not in data:
                continue
                
            delta = data["choices"][0].get("delta", {})
            
            if "content" in delta and delta["content"]:
                full_content += delta["content"]
                
            if "reasoning_content" in delta and delta["reasoning_content"]:
                if full_reasoning_content is None:
                    full_reasoning_content = ""
                full_reasoning_content += delta["reasoning_content"]
                
        except json.JSONDecodeError:
            continue
    
    return ChatCompletionResponse(
        model=model,
        choices=[
            ChatCompletionChoice(
                message=ChatMessage(
                    role="assistant",
                    content=full_content,
                    reasoning_content=full_reasoning_content,
                )
            )
        ],
    )


async def error_stream_generator(error_detail: str, status_code: int):
    """Generate error stream response"""
    yield f'data: {json.dumps({"error": {"message": error_detail, "type": "tenbin_api_error", "code": status_code}})}\n\n'
    yield "data: [DONE]\n\n"


if __name__ == "__main__":
    import uvicorn

    # 设置环境变量以启用调试模式
    if os.environ.get("DEBUG_MODE", "").lower() == "true":
        DEBUG_MODE = True
        print("Debug mode enabled via environment variable")

    if not os.path.exists("tenbin.json"):
        print("Warning: tenbin.json not found. Creating a dummy file.")
        dummy_data = [
            {
                "session_id": "your_session_id_here",
            }
        ]
        with open("tenbin.json", "w", encoding="utf-8") as f:
            json.dump(dummy_data, f, indent=4)
        print("Created dummy tenbin.json. Please replace with valid Tenbin data.")

    if not os.path.exists("client_api_keys.json"):
        print("Warning: client_api_keys.json not found. Creating a dummy file.")
        dummy_key = f"sk-dummy-{uuid.uuid4().hex}"
        with open("client_api_keys.json", "w", encoding="utf-8") as f:
            json.dump([dummy_key], f, indent=2)
        print(f"Created dummy client_api_keys.json with key: {dummy_key}")

    if not os.path.exists("models.json"):
        print("Warning: models.json not found. Creating a dummy file.")
        dummy_models = {
            "claude-3.7-sonnet": "AnthropicClaude37Sonnet",
            "claude-3.7-sonnet-extended": "AnthropicClaude37SonnetExtended"
        }
        with open("models.json", "w", encoding="utf-8") as f:
            json.dump(dummy_models, f, indent=4)
        print("Created dummy models.json.")

    load_client_api_keys()
    load_tenbin_accounts()
    load_tenbin_models()

    print("\n--- Tenbin OpenAI API Adapter ---")
    print(f"Debug Mode: {DEBUG_MODE}")
    print("Endpoints:")
    print("  GET  /v1/models (Client API Key Auth)")
    print("  GET  /models (No Auth)")
    print("  POST /v1/chat/completions (Client API Key Auth)")
    print("  GET  /debug?enable=[true|false] (Toggle Debug Mode)")

    print(f"\nClient API Keys: {len(VALID_CLIENT_KEYS)}")
    if TENBIN_ACCOUNTS:
        print(f"Tenbin Accounts: {len(TENBIN_ACCOUNTS)}")
    else:
        print("Tenbin Accounts: None loaded. Check tenbin.json.")
    if TENBIN_MODELS:
        models = sorted(list(TENBIN_MODELS.keys()))
        print(f"Tenbin Models: {len(TENBIN_MODELS)}")
        print(f"Available models: {', '.join(models[:5])}{'...' if len(models) > 5 else ''}")
    else:
        print("Tenbin Models: None loaded. Check models.json.")
    print("------------------------------------")

    uvicorn.run(app, host="0.0.0.0", port=8000)