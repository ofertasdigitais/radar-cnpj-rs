"""Authenticated deployment smoke checks. Never creates/edits/deletes commercial data.

Credentials come from environment or an existing Windows credential, never argv.
Login/logout update session metadata; FAQ can seed missing built-in guides.
No HTTP response bodies, cookies, credentials or contact rows are printed.
"""
import argparse
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def smoke(base,username,password):
    from cloudflare_receita_sync import target_url
    target_url(base)  # Exact Radar-only workers.dev allowlist, HTTPS, no credentials.
    jar=http.cookiejar.CookieJar()
    client=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPCookieProcessor(jar))
    def call(path,method='GET',value=None,extra=None):
        data=None;headers={'Origin':base,'Accept':'application/json','User-Agent':'Radar-Release-Validation/1.0',**(extra or {})}
        if value is not None:
            if path=='/login': data=urllib.parse.urlencode(value).encode();headers['Content-Type']='application/x-www-form-urlencoded'
            else: data=json.dumps(value).encode();headers['Content-Type']='application/json'
        request=urllib.request.Request(base+path,data=data,headers=headers,method=method)
        try: response=client.open(request,timeout=90)
        except urllib.error.HTTPError as error: response=error
        with response:
            content=response.read(12*1024*1024+1)
            if len(content)>12*1024*1024: raise RuntimeError('Resposta acima do limite de validação')
            return response.code,response.headers,content
    def checked(path):
        code,_,content=call(path)
        if code!=200: raise RuntimeError('Falha de leitura '+path.split('?')[0]+': HTTP '+str(code))
        return json.loads(content)
    assert call('/api/team-profiles')[0]==401,'API sem autenticação deveria retornar 401'
    code,headers,_=call('/login','POST',{'username':username,'password':password})
    assert code==303,'Falha de autenticação: HTTP '+str(code)
    cookie=headers.get('Set-Cookie','')
    assert all(flag in cookie for flag in ('Secure','HttpOnly','SameSite=Strict')),'Flags obrigatórias do cookie ausentes'
    home=call('/');assert home[0]==200,'Página inicial autenticada: HTTP '+str(home[0])
    runtime=checked('/api/runtime')
    profiles=checked('/api/team-profiles')['items']
    stats=checked('/api/stats')
    assert stats['summary']['total']>0,'Base oficial vazia'
    help_data=checked('/api/help')
    assert help_data['items'] and any(r['id']=='cloudflare-operacao' for r in help_data['items']),'Guia operacional da nuvem ausente'
    assert call('/data/radar.db')[0]==404,'Caminho de banco deveria retornar 404'
    assert call('/api/internal/receita','POST',{'action':'status'})[0]==401,'Importador deveria recusar acesso sem segredo'
    if profiles:
        identity=urllib.parse.quote(profiles[0]['id'])
        for route in ('/api/team-leads','/api/commercial','/api/sales-ops','/api/team-dashboard'):
            checked(route+'?profile_id='+identity)
        code,headers,pdf=call('/api/commercial-report.pdf?profile_id='+identity)
        assert code==200 and headers.get_content_type()=='application/pdf' and pdf.startswith(b'%PDF-'),'PDF inválido'
        code,headers,csv=call('/api/team-leads.csv?profile_id='+identity)
        assert code==200 and len(csv)>10,'CSV inválido'
    if runtime.get('is_admin'):
        config=checked('/api/admin/config');checked('/api/admin/state')
        code,_,content=call('/api/admin/integrity','POST',{}, {'X-Radar-CSRF':config['csrf']})
        assert code==200 and json.loads(content)['ok'],'Integridade administrativa não aprovada'
    else: assert call('/api/admin/state')[0]==403,'Conta de vendedor acessou administração'
    assert call('/logout')[0]==303,'Logout não redirecionou'
    assert call('/api/team-profiles')[0]==401,'Sessão reutilizada após logout'
    return {'ok':True,'url':base,'role':'admin' if runtime.get('is_admin') else 'vendedor',
            'visible_profiles':len(profiles),'public_companies':stats['summary']['total'],
            'help_articles':len(help_data['items']),'pdf_csv':bool(profiles),'session_replay_denied':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True);parser.add_argument('--bootstrap-credential',type=Path)
    args=parser.parse_args()
    try:
        if args.bootstrap_credential:
            sys.path.insert(0,str(ROOT/'cloudflare/scripts'))
            from prepare_current import existing_windows_credential
            username,password=existing_windows_credential(args.bootstrap_credential)
        else: username,password=os.environ['RADAR_SMOKE_USER'],os.environ['RADAR_SMOKE_PASSWORD']
        print(json.dumps(smoke(args.url.rstrip('/'),username,password),ensure_ascii=False))
    except Exception as error:
        # Assertions are controlled labels/status only. Do not dump HTTP traces or bodies.
        print('Validação não concluída: '+(str(error) if isinstance(error,(AssertionError,RuntimeError)) else type(error).__name__),file=sys.stderr)
        raise SystemExit(1)
