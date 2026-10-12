"""Interactive, hidden-entry local API configuration (no shell sourcing)."""
from getpass import getpass
import json
from pathlib import Path
from credit_review.workbench.gateway import PROJECT,load_settings
from credit_review.workbench.provider.config import Settings,read_env

def main():
    old=load_settings()
    base=input(f'API URL [{old.base_url}]: ').strip() or old.base_url
    model=input(f'模型 [{old.model}]: ').strip() or old.model
    wire=input(f'协议 responses/chat_completions [{old.wire_api}]: ').strip() or old.wire_api
    key=getpass('新 Key（输入隐藏，留空保留）: ').strip() or old.api_key
    stream=wire=='responses'
    config=Settings(api_key=key,base_url=base,model=model,wire_api=wire,headers=old.headers,stream=stream,structured=False)
    config.validate()
    env=read_env(PROJECT/'.env')
    env.update(LLM_API_KEY=key,LLM_BASE_URL=base,LLM_MODEL=model,LLM_WIRE_API=wire,LLM_STREAM=str(stream).lower(),LLM_STRUCTURED_OUTPUT='false',LLM_HTTP_HEADERS=json.dumps(old.headers))
    target=PROJECT/'.env';target.touch(mode=0o600,exist_ok=True);target.chmod(0o600)
    target.write_text('\n'.join(k+'='+v for k,v in env.items())+'\n',encoding='utf-8')
    print('已保存本机配置。正在运行的任务完成后生效；请在模型管理中测试连通性。')
if __name__=='__main__':main()
