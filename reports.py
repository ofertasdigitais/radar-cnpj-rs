"""Local PDF generation; values come from recorded seller data only."""
from io import BytesIO
from html import escape
from datetime import datetime


def commercial_pdf(profile_name, data, branding=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
    buffer = BytesIO(); styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('RadarTitle', fontName='Helvetica-Bold', fontSize=22, leading=27, textColor=colors.HexColor('#b82043'), spaceAfter=12))
    styles.add(ParagraphStyle('RadarCell', fontName='Helvetica', fontSize=9, leading=12))
    styles['Heading2'].spaceBefore=6;styles['Heading2'].spaceAfter=5
    doc = SimpleDocTemplate(buffer,pagesize=landscape(A4),rightMargin=30,leftMargin=30,topMargin=34,bottomMargin=34)
    text = lambda value: Paragraph(escape(str(value if value is not None else '-')),styles['RadarCell'])
    money = lambda cents: ('R$ '+f'{cents/100:,.2f}').replace(',','X').replace('.',',').replace('X','.')
    def date(value):
        if not value:return 'Sem prazo'
        try:return datetime.fromisoformat(value).strftime('%d/%m/%Y %H:%M')
        except ValueError:return value
    percent = lambda value: str(value).replace('.',',')+'%'
    branding=branding or {}
    story = [Paragraph(escape(branding.get('site_name','RADAR CNPJ')+' | '+branding.get('report_title','Relatório comercial')), styles['RadarTitle']),text(profile_name),Spacer(1,8)]
    period = data['period']; summary = data['summary']
    story += [text(f"Emitido em {date(data['generated_at'])} | Entradas de {period['from'] or 'início'} até {period['to'] or 'hoje'} | Campanha: {period['campaign'] or 'todas'}"),
              text('Coorte por data de entrada. Receita: somente leads convertidos; pipeline: somente oportunidades ativas. Valores registrados, não estimados.'),Spacer(1,14)]

    def table(headers, rows, widths):
        tab = Table([[text(x) for x in headers]]+[[text(x) for x in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
        tab.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#f5e5eb')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('BOX',(0,0),(-1,-1),.5,colors.HexColor('#d9cbd2')),('INNERGRID',(0,0),(-1,-1),.3,colors.HexColor('#d9cbd2')),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
        return tab

    story += [table(['Leads','Ativos','Contatados','Conversão','Pipeline','Receita fechada'],
        [[summary['total'],summary['active'],summary['contacted'],percent(summary['conversion_pct']),money(summary['pipeline_cents']),money(summary['closed_cents'])]], [110,100,120,110,170,170]),Spacer(1,12),
        text(f"Primeiro contato: {summary['avg_first_contact_hours'] if summary['avg_first_contact_hours'] is not None else '-'} horas em média | Fechamento: {summary['avg_close_days'] if summary['avg_close_days'] is not None else '-'} dias | Retornos vencidos: {summary['overdue']}"),Spacer(1,16)]
    for field,label in [('campaign','Campanhas'),('segmento','Segmentos'),('persona','Personas'),('lead_origin','Origens')]:
        story += [Paragraph(label,styles['Heading2']),table(['Grupo','Leads','Conversão','Fechados','Receita'],
            [[x['label'],x['total'],percent(x['conversion_pct']),x['won'],money(x['closed_cents'])] for x in data['breakdown'][field]] or [['Sem registros',0,'0%',0,money(0)]], [350,80,110,80,160])]
        if field!='lead_origin': story.append(Spacer(1,6))
    story += [PageBreak(),Paragraph('Fila de trabalho e qualidade',styles['RadarTitle']),text('Todos os itens prioritários do recorte selecionado.'),Spacer(1,12),
        table(['Empresa','CNPJ','Motivos','Prazo'],[[x['company'],x['cnpj'],'; '.join(x['reasons']),date(x['due'])] for x in data['queue']] or [['Nenhuma pendência','','','']], [240,120,280,140]),Spacer(1,16),
        Paragraph('Motivos de perda',styles['Heading2']),table(['Motivo','Leads'],[[x['label'],x['total']] for x in data['loss_reasons']] or [['Sem perdas registradas',0]],[600,180]),Spacer(1,12),
        KeepTogether([text(f"Telefones com formato improvável: {data['quality']['invalid_phone']} | WhatsApp confirmado pelo vendedor: {data['quality']['whatsapp_confirmed']} | Sem próxima ação: {data['quality']['missing_followup']}"),
        text('Formato de telefone não confirma existência no WhatsApp. Histórico antigo não é reconstruído ou inventado.')])]

    def footer(canvas, doc):
        canvas.saveState(); canvas.setFont('Helvetica',9);canvas.setFillColor(colors.HexColor('#686269'))
        canvas.drawString(30,18,branding.get('site_name','RADAR CNPJ')+' | '+branding.get('report_footer','Uso interno - dados privados do responsável'))
        canvas.drawRightString(810,18,f'Página {doc.page}');canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()
