"""Isolated functional QA server. Never loads or writes the user's database."""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
import commercial
from reports import commercial_pdf


def seed():
    app.init_db()
    now=datetime.now()
    with app.connect() as db:
        db.execute("INSERT INTO sales_profiles(id,name,role,email,owner_id,created_at,updated_at) VALUES('qa-preview','Vendedor de demonstração','QA','', 'local-default',?,?)",(now.isoformat(),now.isoformat()))
        for i in range(96):
            cnpj=f'{99000000000000+i:014d}';stage=['novo','contatado','negociacao','convertido','descartado'][i%5]
            db.execute('''INSERT INTO companies(cnpj,razao_social,nome_fantasia,uf,municipio,situacao,telefone,email,cnae,cnae_descricao,segmento,mei,data_abertura)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(cnpj,'Empresa QA '+str(i)+' com nome comprido e caracteres especiais & comércio','Loja demonstração '+str(i),'RS',['Porto Alegre','Caxias do Sul','Santa Maria'][i%3],'ATIVA','51987654321','teste@example.invalid','4712100','Comércio varejista de mercadorias em geral','Comércio',i%2,(now-timedelta(days=15)).date().isoformat()))
            added=(now-timedelta(days=14+i%10)).isoformat(timespec='seconds');contact=(now-timedelta(days=5)).isoformat(timespec='seconds') if i%5 else None
            db.execute('''INSERT INTO sales_profile_leads(profile_id,cnpj,lead_status,added_at,updated_at,first_contact_at,last_contact_at,next_action,next_action_at,offered_value_cents,negotiated_value_cents,closed_value_cents,closed_at,campaign,persona,lead_origin,loss_reason)
                VALUES('qa-preview',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(cnpj,stage,added,added,contact,contact,'Enviar proposta' if i%3 else '',(now-timedelta(days=i%4)).isoformat(timespec='minutes') if i%3 else None,250000,180000,150000 if stage=='convertido' else 0,contact if stage=='convertido' else None,['Comércio Outubro','Indústria Outubro'][i%2],'Proprietário','Receita Federal','preco' if stage=='descartado' else ''))
            app.add_lead_history(db,'qa-preview',cnpj,'created','Lead de demonstração incluído','',added)
        data=commercial.analytics(db,'qa-preview')
    output=Path('tmp/pdfs');output.mkdir(parents=True,exist_ok=True)
    (output/'qa-relatorio.pdf').write_bytes(commercial_pdf('Demonstração de layout - dados fictícios',data))


if __name__=='__main__':
    os.environ['RADAR_ADMIN_USER']='';os.environ['RADAR_ADMIN_PASSWORD']=''
    with tempfile.TemporaryDirectory(prefix='radar-qa-') as directory:
        app.DB=Path(directory)/'demo.sqlite';seed()
        app.SYNC.db_path=app.DB;app.MONITOR.db_path=app.DB
        server=app.ThreadingHTTPServer(('127.0.0.1',18000),app.Handler)
        print('QA isolado: http://127.0.0.1:18000/#leads',flush=True)
        try:server.serve_forever()
        finally:server.server_close()
