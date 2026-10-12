from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def read_env(path: Path) -> dict:
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:]
        key, sep, value = line.partition('=')
        if not sep or not key.strip().replace('_', '').isalnum():
            raise ValueError('.env 格式错误：每行使用 NAME=value')
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    base_url: str = 'https://api.openai.com/v1'
    model: str = 'gpt-4.1-mini'
    wire_api: str = 'responses'
    headers: dict = field(default_factory=dict, repr=False)
    stream: bool = False
    timeout: float = 60
    retries: int = 2
    max_tokens: int = 4096
    structured: bool = True

    @classmethod
    def load(cls, env_file: Path | None = None) -> Settings:
        values = {**read_env(env_file or ROOT / '.env'), **os.environ}
        return cls(
            api_key=values.get('LLM_API_KEY') or values.get('OPENAI_API_KEY', ''),
            base_url=values.get('LLM_BASE_URL', 'https://api.openai.com/v1'),
            model=values.get('LLM_MODEL', 'gpt-4.1-mini'),
            wire_api=values.get('LLM_WIRE_API', 'responses'),
            headers=json.loads(values.get('LLM_HTTP_HEADERS', '{}')),
            stream=values.get('LLM_STREAM', 'false').lower() == 'true',
            timeout=float(values.get('LLM_TIMEOUT', '60')),
            retries=int(values.get('LLM_RETRIES', '2')),
            max_tokens=int(values.get('LLM_MAX_TOKENS', '4096')),
            structured=values.get('LLM_STRUCTURED_OUTPUT', 'true').lower() == 'true',
        )

    def validate(self):
        if not self.api_key or self.api_key in {'your-key-here', 'REMOVED_USE_ENV'}:
            raise ValueError('尚未配置有效 Key。请在 .env 设置 LLM_API_KEY。')
        if any(c in self.api_key for c in '\r\n'):
            raise ValueError('Key 不能含换行')
        url = urlparse(self.base_url)
        if url.username or url.password or url.query or url.fragment:
            raise ValueError('LLM_BASE_URL 不得包含凭据、查询参数或片段')
        if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in {'localhost', '127.0.0.1', '::1'}):
            raise ValueError('远程 API 必须使用 HTTPS')
        if not url.hostname or not self.model:
            raise ValueError('请配置 LLM_BASE_URL 和 LLM_MODEL')
        if self.wire_api not in {'responses', 'chat_completions'}:
            raise ValueError('LLM_WIRE_API 必须为 responses/chat_completions')
        if self.stream and self.wire_api != 'responses':
            raise ValueError('流式模式当前仅用于 Responses API')
        if not 0 < self.timeout <= 300 or not 0 <= self.retries <= 5 or not 64 <= self.max_tokens <= 32768:
            raise ValueError('API 超时、重试或输出上限超出允许范围')
        if not isinstance(self.headers, dict):
            raise ValueError('LLM_HTTP_HEADERS 必须为 JSON 对象')
        for key, value in self.headers.items():
            if not isinstance(key, str) or not isinstance(value, str) or any(c in key + value for c in '\r\n'):
                raise ValueError('额外请求头必须为无换行的字符串')
            if key.lower() in {'authorization', 'host', 'content-length', 'content-type'}:
                raise ValueError('额外请求头不得覆盖认证或传输字段')

    def public(self):
        return {'base_url': self.base_url, 'model': self.model, 'wire_api': self.wire_api,
                'key_configured': bool(self.api_key), 'stream': self.stream,
                'structured_output': self.structured, 'extra_header_names': list(self.headers),
                'timeout_seconds': self.timeout, 'retries': self.retries, 'max_output_tokens': self.max_tokens}
