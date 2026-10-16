"""Provider-neutral real API gateway with redacted, durable call records."""
import json
import os
from dataclasses import replace
from pathlib import Path
from .provider.api import Client, parse_json
from .provider.config import Settings, read_env

PROJECT = Path(__file__).resolve().parents[3]


def load_settings():
    values = {**read_env(PROJECT / '.env'), **os.environ}
    # Keep old DeepSeek-only deployments usable while accepting Responses relays.
    if not values.get('LLM_API_KEY') and values.get('DEEPSEEK_API_KEY'):
        return Settings(api_key=values['DEEPSEEK_API_KEY'], base_url=values.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com'),
                        model=values.get('DEEPSEEK_MODEL', 'deepseek-chat'), wire_api='chat_completions', structured=False)
    return Settings.load(PROJECT / '.env')


class Gateway:
    def __init__(self, store=None, job=None, config=None):
        self.config = config or load_settings()
        self.client = Client(self.config)
        self.store, self.job = store, job
        self.client.observer = lambda event: self.record('provider_http_attempt', event)

    def record(self, stage, body):
        if self.store and self.job:
            self.store.append(self.job, stage, body)

    def complete_json(self, messages):
        system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
        user = '\n'.join(m['content'] for m in messages if m['role'] != 'system')
        request = {'configuration': self.config.public(), 'messages': messages,
                   'purpose': '可审计摘要与结构化结果；不保存模型内部思维链'}
        self.record('model_request', request)
        before = dict(self.client.usage)
        try:
            text = self.client.complete(system, user)
            self.record('model_response', {'text': text, 'usage': {k: self.client.usage[k] - before[k] for k in before}})
            try:
                return parse_json(text)
            except Exception as parse_error:
                # A single syntax retry, never a fallback verdict or JSON repair
                # that could silently change financial values or source quotes.
                self.record('model_json_retry', {'error':str(parse_error),'attempt_limit':1})
                retry_system=system+' 上次输出不是有效JSON。重新完成同一任务，只输出JSON对象；字符串内的双引号必须用反斜杠转义，无关证据的quote可留空。'
                self.record('model_request', {**request,'messages':[{'role':'system','content':retry_system},{'role':'user','content':user}],'syntax_retry':True})
                before_retry=dict(self.client.usage)
                retry_text=self.client.complete(retry_system,user)
                self.record('model_response', {'text':retry_text,'syntax_retry':True,'usage':{k:self.client.usage[k]-before_retry[k] for k in before_retry}})
                return parse_json(retry_text)
        except Exception as exc:
            self.record('model_error', {'error': str(exc), 'type': type(exc).__name__})
            raise

    def healthcheck(self):
        return self.client.complete('只回复 OK。', '检查 API 连通性。')
