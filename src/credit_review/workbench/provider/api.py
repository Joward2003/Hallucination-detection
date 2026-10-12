from __future__ import annotations
import json
import socket
import time
import urllib.error
import urllib.request
from .config import Settings


class APIError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith('```'):
        lines = text.splitlines()
        if lines[-1].strip() == '```':
            text = '\n'.join(lines[1:-1])
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise APIError('模型未返回有效 JSON；本次测评未生成判定') from exc
    if not isinstance(obj, dict):
        raise APIError('模型 JSON 必须为对象')
    return obj


def response_text(data: dict) -> str:
    if data.get('status') != 'completed':
        raise APIError('Responses 请求未完整完成；检查输出上限或服务状态')
    output = data.get('output')
    if not isinstance(output, list):
        raise APIError('Responses 缺少 output')
    texts = []
    for item in output:
        if not isinstance(item, dict) or item.get('type') != 'message':
            continue
        for part in item.get('content', []):
            if isinstance(part, dict) and part.get('type') == 'refusal':
                raise APIError('模型拒绝了本次请求')
            if isinstance(part, dict) and part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                texts.append(part['text'])
    text = ''.join(texts)
    if not text.strip():
        raise APIError('API 返回空内容')
    return text


def read_sse(response, deadline: float | None = None) -> dict:
    """Accept only a terminal response.completed; do not treat partial deltas as success."""
    chunk = []
    for raw_line in response:
        if deadline is not None and time.monotonic() > deadline:
            raise APIError('Responses 流超过总时间上限，未收到完成事件')
        line = raw_line.decode('utf-8').rstrip('\r\n')
        if line.startswith('data:'):
            chunk.append(line[5:].lstrip())
        elif not line and chunk:
            payload = '\n'.join(chunk)
            chunk = []
            if payload == '[DONE]':
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                raise APIError('Responses 流中存在无效 JSON') from None
            kind = event.get('type')
            if kind == 'response.completed':
                result = event.get('response')
                if not isinstance(result, dict):
                    raise APIError('Responses 完成事件缺少结果')
                return result
            if kind in {'error', 'response.failed', 'response.incomplete'}:
                raise APIError('Responses 流返回错误或不完整结果')
    raise APIError('Responses 流中断，未收到完成事件')


class Client:
    def __init__(self, settings: Settings):
        settings.validate()
        self.settings = settings
        self.calls = 0
        self.usage = {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}
        self.opener = urllib.request.build_opener(NoRedirect())
        self.observer = None

    def observe(self, event):
        if self.observer is not None:
            self.observer(event)

    def complete(self, system: str, user: str, schema: dict | None = None) -> str:
        cfg = self.settings
        fmt = {'type': 'json_schema', 'name': 'result', 'strict': True, 'schema': schema} if schema and cfg.structured else None
        if cfg.wire_api == 'responses':
            path = '/responses'
            payload = {'model': cfg.model, 'instructions': system,
                       'input': [{'role': 'user', 'content': [{'type': 'input_text', 'text': user}]}],
                       'max_output_tokens': cfg.max_tokens, 'store': False, 'stream': cfg.stream}
            if fmt:
                payload['text'] = {'format': fmt}
        else:
            path = '/chat/completions'
            payload = {'model': cfg.model, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                       'max_completion_tokens': cfg.max_tokens, 'stream': False}
            if fmt:
                payload['response_format'] = {'type': 'json_schema', 'json_schema': {k: v for k, v in fmt.items() if k != 'type'}}
        request = urllib.request.Request(cfg.base_url.rstrip('/') + path,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Authorization': 'Bearer ' + cfg.api_key, 'Content-Type': 'application/json', **cfg.headers})
        hints = {400: '参数、模型或结构化输出不兼容', 401: 'Key 无效或已失效', 402: '余额不足',
                 403: 'Key 未获授权或访问受限', 404: '模型或接口不存在', 410: '接口已停用', 429: '限流或配额不足'}
        for attempt in range(cfg.retries + 1):
            self.calls += 1
            started = time.monotonic()
            self.observe({'type': 'http_attempt_start', 'attempt': attempt + 1, 'path': path, 'model': cfg.model, 'wire_api': cfg.wire_api})
            try:
                with self.opener.open(request, timeout=cfg.timeout) as response:
                    if 'text/event-stream' in response.headers.get('Content-Type', ''):
                        data = read_sse(response, time.monotonic() + cfg.timeout)
                    else:
                        data = json.load(response)
            except urllib.error.HTTPError as exc:
                code = exc.code
                exc.close()
                self.observe({'type': 'http_attempt_error', 'attempt': attempt + 1, 'http_status': code, 'elapsed_ms': (time.monotonic() - started) * 1000})
                if (code == 429 or 500 <= code < 600) and attempt < cfg.retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise APIError(f'API HTTP {code}：{hints.get(code, "服务错误或拒绝重定向")}') from None
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
                self.observe({'type': 'http_attempt_error', 'attempt': attempt + 1, 'error': 'network_or_timeout', 'elapsed_ms': (time.monotonic() - started) * 1000})
                if attempt < cfg.retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise APIError('API 网络连接失败或超时') from None
            except (ValueError, OSError):
                self.observe({'type': 'http_attempt_error', 'attempt': attempt + 1, 'error': 'invalid_response', 'elapsed_ms': (time.monotonic() - started) * 1000})
                raise APIError('API 响应不可解析或连接中断') from None
            except APIError as exc:
                self.observe({'type': 'http_attempt_error', 'attempt': attempt + 1, 'error': str(exc), 'elapsed_ms': (time.monotonic() - started) * 1000})
                raise
            if not isinstance(data, dict):
                raise APIError('API 响应必须为对象')
            usage = data.get('usage') or {}
            self.observe({'type': 'http_attempt_response', 'attempt': attempt + 1, 'response_id': data.get('id'), 'status': data.get('status'), 'usage': usage, 'elapsed_ms': (time.monotonic() - started) * 1000})
            for target, source in [('input_tokens', 'input_tokens' if cfg.wire_api == 'responses' else 'prompt_tokens'),
                                   ('output_tokens', 'output_tokens' if cfg.wire_api == 'responses' else 'completion_tokens'),
                                   ('total_tokens', 'total_tokens')]:
                value = usage.get(source) if isinstance(usage, dict) else None
                if isinstance(value, int) and value >= 0:
                    self.usage[target] += value
            if cfg.wire_api == 'responses':
                return response_text(data)
            choices = data.get('choices')
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise APIError('API 响应缺少 choices')
            if choices[0].get('finish_reason') != 'stop':
                raise APIError('模型输出未正常结束')
            message = choices[0].get('message')
            content = message.get('content') if isinstance(message, dict) else None
            if not isinstance(content, str) or not content.strip():
                raise APIError('API 返回空内容')
            return content
        raise APIError('API 重试失败')

    def json(self, system: str, user: str, schema: dict | None = None):
        return parse_json(self.complete(system, user, schema))
