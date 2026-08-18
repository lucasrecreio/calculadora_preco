import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import io
import re

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Mega Rio | Deal Desk", layout="wide", page_icon="📊")

st.markdown(
    '<style>'
    '[data-testid="stMetricValue"] { font-size: 1.4rem !important; } '
    '[data-testid="stMetricDelta"] { font-size: 0.85rem !important; } '
    '.info-box { background-color: #1a1a2e; border-left: 3px solid #636efa; padding: 12px 16px; border-radius: 4px; margin: 8px 0; } '
    '</style>', 
    unsafe_allow_html=True
)

# --- CAMINHOS DOS ARQUIVOS ---
# Teste local (para a nuvem, você pode mudar para "dados/8125_dados_cadastro_produto.csv" se colocar numa pasta)
caminho_base = r"8125_dados_cadastro_produto.csv"

# --- FUNÇÕES AUXILIARES ---
def parse_lista_codigos(texto_input):
    if not texto_input: return []
    return [x.strip() for x in re.split(r'[,\n]+', str(texto_input)) if x.strip()]

# --- FUNÇÕES DE CARREGAMENTO E DADOS (Pandas Nativo) ---
@st.cache_data(show_spinner=False)
def carregar_base_produtos(caminho):
    try:
        # Forçamos a leitura do EAN como string para evitar notação científica ou arredondamento
        try:
            df = pd.read_csv(caminho, sep=';', decimal=',', encoding='utf-8', low_memory=False, dtype={'CODPROD': str, 'EAN': str})
            if len(df.columns) == 1: 
                df = pd.read_csv(caminho, sep='\t', decimal=',', encoding='utf-8', low_memory=False, dtype={'CODPROD': str, 'EAN': str})
        except UnicodeDecodeError:
            df = pd.read_csv(caminho, sep=';', decimal=',', encoding='latin1', low_memory=False, dtype={'CODPROD': str, 'EAN': str})
            if len(df.columns) == 1:
                df = pd.read_csv(caminho, sep='\t', decimal=',', encoding='latin1', low_memory=False, dtype={'CODPROD': str, 'EAN': str})
            
        if 'CODPROD' in df.columns:
            df['CODPROD'] = df['CODPROD'].astype(str).str.split('.').str[0]
            
        # BLINDAGEM DO EAN (Mantém estritamente como texto e remove '.0' final)
        if 'EAN' in df.columns:
            df['EAN'] = df['EAN'].astype(str).str.replace(r'\.0$', '', regex=True)
            df['EAN'] = df['EAN'].replace(['nan', 'NaN', 'None', ''], '-')
            
        cols_numericas = ['CUSTO_ULT_ENT', 'PERC_ICMS', 'PERCPIS', 'PERCCOFINS', 'PVENDAST', 'PERC_ST', 'QTD_CX', 'QTESTDISP']
        
        for col in cols_numericas:
            if col in df.columns:
                if df[col].dtype == 'object':
                    df[col] = df[col].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
        return df
    except Exception as e:
        return pd.DataFrame()

# Carrega a base
df_base = carregar_base_produtos(caminho_base)

if df_base.empty or len(df_base.columns) == 0:
    st.error(f"⚠️ Não foi possível ler a base de produtos. Verifique se o caminho do arquivo está correto: `{caminho_base}`")
    st.stop()

# --- FUNÇÕES DE BUSCA ---
@st.cache_data(show_spinner=False)
def buscar_produto(codigo, df_in):
    res = df_in[df_in['CODPROD'] == codigo].copy()
    if not res.empty:
        agg_res = {
            'DESCRICAO': res['PRODUTO'].max(),
            'MARCA': res['MARCA'].max() if 'MARCA' in res.columns else "-",
            'EAN': res['EAN'].max() if 'EAN' in res.columns else "-",
            'CUSTO_ULT_ENT': res['CUSTO_ULT_ENT'].max(),
            'PERC_ICMS': res['PERC_ICMS'].max(),
            'PERCPIS': res['PERCPIS'].max(),
            'PERCCOFINS': res['PERCCOFINS'].max(),
            'PERC_ST': res['PERC_ST'].max(),
            'PVENDAST': res['PVENDAST'].max(),
            'QTD_CX': res['QTD_CX'].max() if pd.notna(res['QTD_CX'].max()) and res['QTD_CX'].max() > 0 else 1,
            'ESTOQUE_CX': res['QTESTDISP'].max()
        }
        return pd.DataFrame([agg_res])
    return pd.DataFrame()

@st.cache_data(show_spinner=False)
def listar_marcas(df_in):
    if 'MARCA' not in df_in.columns:
        return []
    marcas = df_in['MARCA'].dropna().unique().tolist()
    return sorted([str(m) for m in marcas if str(m).strip() != ''])
    
@st.cache_data(show_spinner=False)
def listar_produtos_dropdown(df_in, marca=None):
    df_filt = df_in.dropna(subset=['PRODUTO']).copy()
    df_filt = df_filt[df_filt['PRODUTO'].str.strip() != '']
    
    if marca:
        df_filt = df_filt[df_filt['MARCA'] == marca]
        
    df_filt['COD_NUM'] = pd.to_numeric(df_filt['CODPROD'], errors='coerce')
    df_filt = df_filt.sort_values('COD_NUM')
    
    return (df_filt['CODPROD'].astype(str) + " - " + df_filt['PRODUTO']).tolist()


# --- INTERFACE PRINCIPAL ---
st.title("🧮 Deal Desk | Simulador de Negociações")
st.markdown("Avalie a rentabilidade dos produtos e simule o impacto de descontos, impostos e verbas comerciais (VPC) no pedido final.")

tab_deal, tab_waterfall = st.tabs([
    "🤝 Carrinho de Negociação",
    "📊 Diagnóstico Unitário"
])

# ==========================================
# TAB 1: CARRINHO DE NEGOCIAÇÃO
# ==========================================
with tab_deal:
    if 'carrinho_deal' not in st.session_state:
        st.session_state['carrinho_deal'] = []

    st.subheader("1. Simulador de Rentabilidade por Produto")
    
    tab_item, tab_lote = st.tabs(["🛒 Inserir Manualmente", "📁 Subir Planilha em Lote"])
    
    # === ABA INTERNA 1: ITEM A ITEM ===
    with tab_item:
        st.write("**🔍 Busque o Produto:**")
        col_busca1, col_busca2, col_busca3 = st.columns([1, 1, 2])
        
        with col_busca1:
            lista_marcas = listar_marcas(df_base)
            marca_selecionada = st.selectbox("Filtro por Marca:", lista_marcas, index=None, placeholder="Todas as marcas...")
            
        with col_busca2:
            filtro_carrinho = st.text_input("Filtro Rápido (Texto):", "", placeholder="Ex: azeite", help="Digite qualquer parte do nome para filtrar a lista.")
            
        lista_produtos_raw = listar_produtos_dropdown(df_base, marca_selecionada)
        
        if filtro_carrinho:
            lista_produtos_filtrada = [p for p in lista_produtos_raw if filtro_carrinho.upper() in p.upper()]
        else:
            lista_produtos_filtrada = lista_produtos_raw
            
        with col_busca3:
            produto_selecionado = st.selectbox("Selecione o Produto:", lista_produtos_filtrada, index=None, placeholder="Selecione um produto...")
        
        if produto_selecionado:
            cod_prod_sim = produto_selecionado.split(" - ")[0].strip()
            
            try:
                df_prod = buscar_produto(cod_prod_sim, df_base)
                
                if not df_prod.empty and pd.notna(df_prod['DESCRICAO'].iloc[0]):
                    p_desc = df_prod['DESCRICAO'].iloc[0]
                    p_marca = df_prod['MARCA'].iloc[0]
                    p_ean = df_prod['EAN'].iloc[0]
                    p_custo = float(df_prod['CUSTO_ULT_ENT'].iloc[0] or 0.0)
                    p_icms = float(df_prod['PERC_ICMS'].iloc[0] or 0.0)
                    p_pis = float(df_prod['PERCPIS'].iloc[0] or 0.0)
                    p_cofins = float(df_prod['PERCCOFINS'].iloc[0] or 0.0)
                    p_st = float(df_prod['PERC_ST'].iloc[0] or 0.0)
                    p_preco_atual = float(df_prod['PVENDAST'].iloc[0] or 0.0)
                    p_qtd_cx = int(df_prod['QTD_CX'].iloc[0] or 1)
                    p_estoque = int(df_prod['ESTOQUE_CX'].iloc[0] or 0)
                    
                    preco_sem_st_erp = p_preco_atual / (1 + (p_st / 100)) if (1 + (p_st / 100)) > 0 else p_preco_atual
                    
                    st.markdown(f"""
                    <div style="background-color: #2b303b; border-left: 5px solid #00cc96; padding: 15px; border-radius: 5px; color: #ffffff; margin-bottom: 20px;">
                        <h4 style="margin: 0 0 10px 0; color: #ffffff;">{p_desc}</h4>
                        <span style="font-size: 14px;">
                            <b>Marca:</b> {p_marca} &nbsp;|&nbsp;
                            <b>EAN:</b> {p_ean} &nbsp;|&nbsp;
                            <b>Custo Base:</b> R$ {p_custo:.2f} &nbsp;|&nbsp; 
                            <b>Preço ERP (Com ST):</b> R$ {p_preco_atual:.2f} &nbsp;|&nbsp; 
                            <b>Preço ERP (Sem ST):</b> R$ {preco_sem_st_erp:.2f} <br>
                            <b>Unidades p/ Caixa:</b> {p_qtd_cx} &nbsp;|&nbsp; 
                            <b>Estoque Disp.:</b> {p_estoque} Cx
                        </span>
                    </div>
                    """, unsafe_allow_html=True)

                    st.write("**Ajustar Despesas Variáveis (%)**")
                    cd1, cd2, cd3, cd4 = st.columns(4)
                    pct_descarga = cd1.number_input("Descarga (%)", value=0.0, step=0.5)
                    pct_op_logistico = cd2.number_input("Op. Logístico (%)", value=5.0, step=0.5)
                    pct_comissao = cd3.number_input("Comissão (%)", value=0.0, step=0.5)
                    pct_outros = cd4.number_input("Outros (%)", value=0.0, step=0.5)

                    FOT_BASE = 22.0
                    FOT_ALIQ = 18.18
                    
                    aliq_icms = p_icms / 100.0
                    aliq_pis_cofins = (p_pis + p_cofins) / 100.0
                    pis_cofins_efetivo = (1 - aliq_icms) * aliq_pis_cofins
                    fot_efetivo = ((FOT_BASE - p_icms) * FOT_ALIQ) / 10000.0
                    st_efetivo = p_st / 100.0
                    desp_operacionais_efetivas = (pct_descarga + pct_op_logistico + pct_comissao + pct_outros) / 100.0

                    def calc_resultado(preco_teste):
                        preco_sem_st = preco_teste / (1 + st_efetivo)
                        vlr_icms = preco_sem_st * aliq_icms
                        base_pis_cofins = preco_sem_st - vlr_icms
                        vlr_pis = base_pis_cofins * (p_pis / 100.0)
                        vlr_cofins = base_pis_cofins * (p_cofins / 100.0)
                        vlr_fot = ((preco_sem_st * (FOT_BASE / 100.0)) - vlr_icms) * (FOT_ALIQ / 100.0)
                        
                        impostos_totais_sem_st = vlr_icms + vlr_pis + vlr_cofins + vlr_fot
                        despesas_rs = preco_sem_st * desp_operacionais_efetivas
                        
                        cmv_total = p_custo + impostos_totais_sem_st + despesas_rs 
                        
                        lucro = preco_sem_st - cmv_total
                        margem = (lucro / preco_sem_st) * 100.0 if preco_sem_st > 0 else 0
                        return lucro, margem

                    st.markdown("---")
                        
                    col_sim1, col_sim2 = st.columns(2)
                    
                    with col_sim1:
                        st.write("**🎯 Modo A: Descobrir preço pela Margem Desejada**")
                        margem_alvo = st.number_input("Margem Líquida Alvo (%)", value=5.0, step=0.5) / 100.0
                        
                        aliq_totais_sem_st = aliq_icms + pis_cofins_efetivo + fot_efetivo + desp_operacionais_efetivas
                        denominador = 1 - (aliq_totais_sem_st + margem_alvo)
                        
                        preco_sugerido = 0.0
                        if denominador > 0 and p_custo > 0:
                            preco_sem_st_alvo = p_custo / denominador
                            preco_sugerido = preco_sem_st_alvo * (1 + st_efetivo)
                            st.success(f"Preço Sugerido (Alvo): **R$ {preco_sugerido:.2f}**")
                        else:
                            st.error("Margem inviável com os custos atuais.")

                    with col_sim2:
                        st.write("**📝 Modo B: Avaliar Preço Solicitado pelo Vendedor**")
                        preco_negociado = st.number_input("Preço Fechado na Negociação (R$)", value=float(p_preco_atual), step=0.50)
                        
                        if preco_negociado > 0:
                            lucro_rs, margem_real = calc_resultado(preco_negociado)
                            if margem_real >= 5.0:
                                st.info(f"Margem Líquida Parcial: **{margem_real:.2f}%** | Lucro Un.: **R$ {lucro_rs:.2f}**")
                            else:
                                st.error(f"Margem Líquida Parcial: **{margem_real:.2f}%** | Lucro Un.: **R$ {lucro_rs:.2f}**")

                    st.write("**🛒 Adicionar Produto ao Pedido**")
                    col_qtd, col_btn1, col_btn2, col_btn3 = st.columns([1.5, 1.5, 1.5, 1.5])
                    qtd_caixas = col_qtd.number_input("Quantidade de Caixas", min_value=1, value=10, step=1)
                    
                    def add_carrinho(preco_aplicado, tipo_preco):
                        preco_sem_st = preco_aplicado / (1 + st_efetivo)
                        vlr_icms = preco_sem_st * aliq_icms
                        base_pis_cofins = preco_sem_st - vlr_icms
                        vlr_pis = base_pis_cofins * (p_pis / 100.0)
                        vlr_cofins = base_pis_cofins * (p_cofins / 100.0)
                        vlr_fot = ((preco_sem_st * (FOT_BASE / 100.0)) - vlr_icms) * (FOT_ALIQ / 100.0)
                        vlr_st = preco_sem_st * st_efetivo
                        
                        impostos_totais_sem_st = vlr_icms + vlr_pis + vlr_cofins + vlr_fot
                        
                        vlr_descarga = preco_sem_st * (pct_descarga / 100.0)
                        vlr_op_log = preco_sem_st * (pct_op_logistico / 100.0)
                        vlr_comissao = preco_sem_st * (pct_comissao / 100.0)
                        vlr_outros = preco_sem_st * (pct_outros / 100.0)
                        despesas_rs = vlr_descarga + vlr_op_log + vlr_comissao + vlr_outros
                        
                        lucro_un, margem_un = calc_resultado(preco_aplicado)
                        total_unidades = qtd_caixas * p_qtd_cx
                        
                        custo_aquisicao = p_custo * total_unidades
                        
                        cmv_total = custo_aquisicao + (impostos_totais_sem_st * total_unidades) + (despesas_rs * total_unidades)
                        
                        novo_item = {
                            "Código": cod_prod_sim,
                            "Produto": p_desc,
                            "Marca": p_marca,
                            "EAN": p_ean,
                            "Caixas": qtd_caixas,
                            "Unid/CX": p_qtd_cx,
                            "Total Unid": total_unidades,
                            "Preço Unit.": preco_aplicado,
                            "Preço Sem ST": preco_sem_st,
                            "Faturamento Total": preco_aplicado * total_unidades,
                            "Custo de Aquisição": custo_aquisicao,
                            "ICMS": vlr_icms * total_unidades,
                            "PIS/COFINS": (vlr_pis + vlr_cofins) * total_unidades,
                            "FOT": vlr_fot * total_unidades,
                            "ST": vlr_st * total_unidades,
                            "Descarga": vlr_descarga * total_unidades,
                            "Op. Logístico": vlr_op_log * total_unidades,
                            "Comissão": vlr_comissao * total_unidades,
                            "Outros": vlr_outros * total_unidades,
                            "Custo Total (CMV + Desp)": cmv_total,
                            "Lucro Líquido": lucro_un * total_unidades,
                            "Margem %": margem_un / 100.0,
                            "Tipo Preço": tipo_preco
                        }
                        
                        item_existente_idx = next((i for (i, d) in enumerate(st.session_state['carrinho_deal']) if d["Código"] == cod_prod_sim), None)
                        if item_existente_idx is not None:
                            st.session_state['carrinho_deal'][item_existente_idx] = novo_item
                            st.toast(f"🔄 Produto {cod_prod_sim} atualizado no carrinho!")
                        else:
                            st.session_state['carrinho_deal'].append(novo_item)
                            st.toast(f"✅ Produto {cod_prod_sim} adicionado!")
                            
                        st.session_state['ultimo_produto_simulado'] = cod_prod_sim
                        st.rerun()

                    with col_btn1:
                        st.write("") ; st.write("")
                        if st.button("➕ Adicionar Preço Sugerido", help=f"Adicionar por R$ {preco_sugerido:.2f}") and preco_sugerido > 0:
                            add_carrinho(preco_sugerido, "Sugerido")
                    with col_btn2:
                        st.write("") ; st.write("")
                        if st.button("➕ Adicionar Preço Negociado", help=f"Adicionar por R$ {preco_negociado:.2f}"):
                            add_carrinho(preco_negociado, "Negociado")
                    with col_btn3:
                        st.write("") ; st.write("")
                        if st.button("➕ Adicionar Preço Tabela", help=f"Adicionar por R$ {p_preco_atual:.2f}"):
                            add_carrinho(p_preco_atual, "Atual")

                else:
                    st.warning("Produto não encontrado na base.")
            except Exception as e:
                st.error(f"Erro ao processar produto: {e}")

    # === ABA INTERNA 2: UPLOAD EM LOTE ===
    with tab_lote:
        st.info("💡 **Dica:** Filtre as Marcas, Nomes e Códigos abaixo para gerar uma Planilha Modelo já pré-preenchida com os produtos. Se deixar os campos de despesas vazios no preenchimento, o sistema usará o padrão (Ex: Op. Logístico 5%).")
        
        col_fl1, col_fl2, col_fl3 = st.columns([1, 1, 1])
        with col_fl1:
            marcas_lote = st.multiselect("Filtrar por Marcas:", listar_marcas(df_base), placeholder="Selecione as marcas...")
        with col_fl2:
            nome_lote = st.text_input("Filtrar por Nome do Produto:", "", placeholder="Ex: azeite")
        with col_fl3:
            codigos_texto = st.text_area("Filtrar por Códigos (separados por vírgula):", help="Ex: 1768, 12900", height=68, placeholder="Cole a lista de códigos aqui...")
        
        codigos_lista = parse_lista_codigos(codigos_texto)
        
        df_modelo_base = df_base.copy()
        
        if marcas_lote:
            df_modelo_base = df_modelo_base[df_modelo_base['MARCA'].isin(marcas_lote)]
        if nome_lote:
            df_modelo_base = df_modelo_base[df_modelo_base['PRODUTO'].str.contains(nome_lote, case=False, na=False)]
        if codigos_lista:
            df_modelo_base = df_modelo_base[df_modelo_base['CODPROD'].isin(codigos_lista)]
            
        df_modelo_base['COD_NUM'] = pd.to_numeric(df_modelo_base['CODPROD'], errors='coerce')
        df_modelo_base = df_modelo_base.sort_values('COD_NUM')

        with st.spinner("Preparando template..."):
            df_produtos_modelo = df_modelo_base[['CODPROD', 'PRODUTO', 'MARCA', 'EAN', 'QTESTDISP']].rename(columns={'QTESTDISP': 'ESTOQUE_CX'}).copy()
            
            df_produtos_modelo['QTD_CAIXAS'] = None
            df_produtos_modelo['PRECO_NEGOCIADO'] = None
            df_produtos_modelo['MARGEM_ALVO_PCT'] = None
            df_produtos_modelo['DESCARGA_PCT'] = None
            df_produtos_modelo['OP_LOGISTICO_PCT'] = None
            df_produtos_modelo['COMISSAO_PCT'] = None
            df_produtos_modelo['OUTROS_PCT'] = None
            
            buffer_modelo = io.BytesIO()
            with pd.ExcelWriter(buffer_modelo, engine='openpyxl') as writer:
                df_produtos_modelo.to_excel(writer, index=False, sheet_name='Lote')
                
        st.download_button("📥 Baixar Planilha Modelo (Preenchida com Filtros)", data=buffer_modelo.getvalue(), file_name="Modelo_Upload_Pricing.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        
        st.markdown("---")
        arquivo_lote = st.file_uploader("Suba a planilha preenchida (Excel):", type=['xlsx'])
        
        if arquivo_lote:
            try:
                df_upload = pd.read_excel(arquivo_lote)
                df_upload['CODPROD'] = df_upload['CODPROD'].astype(str).str.split('.').str[0]
                
                codigos_lista_up = df_upload['CODPROD'].dropna().tolist()
                
                df_db_lote = df_base[df_base['CODPROD'].isin(codigos_lista_up)].copy()
                df_db_lote = df_db_lote.groupby('CODPROD').agg({
                    'PRODUTO': 'max',
                    'MARCA': 'max',
                    'EAN': 'max',
                    'CUSTO_ULT_ENT': 'max',
                    'PERC_ICMS': 'max',
                    'PERCPIS': 'max',
                    'PERCCOFINS': 'max',
                    'PERC_ST': 'max',
                    'PVENDAST': 'max',
                    'QTD_CX': 'max'
                }).reset_index()
                
                df_db_lote['QTD_CX'] = df_db_lote['QTD_CX'].replace(0, 1).fillna(1)
                
                itens_adicionados = 0 ; itens_atualizados = 0
                
                if st.button("🚀 Processar e Adicionar ao Pedido", use_container_width=True):
                    with st.spinner("Calculando rentabilidade da planilha..."):
                        FOT_BASE = 22.0 ; FOT_ALIQ = 18.18
                        
                        for idx, row in df_upload.iterrows():
                            cod = str(row['CODPROD'])
                            row_db = df_db_lote[df_db_lote['CODPROD'] == cod]
                            
                            if not row_db.empty:
                                p_custo = float(row_db['CUSTO_ULT_ENT'].iloc[0] or 0.0)
                                p_icms = float(row_db['PERC_ICMS'].iloc[0] or 0.0)
                                p_pis = float(row_db['PERCPIS'].iloc[0] or 0.0)
                                p_cofins = float(row_db['PERCCOFINS'].iloc[0] or 0.0)
                                p_st = float(row_db['PERC_ST'].iloc[0] or 0.0)
                                p_preco_atual = float(row_db['PVENDAST'].iloc[0] or 0.0)
                                p_qtd_cx = int(row_db['QTD_CX'].iloc[0] or 1)
                                p_desc = row_db['PRODUTO'].iloc[0]
                                p_marca = row_db['MARCA'].iloc[0] if pd.notna(row_db['MARCA'].iloc[0]) else "-"
                                p_ean = row_db['EAN'].iloc[0] if pd.notna(row_db['EAN'].iloc[0]) else "-"
                                
                                qtd_raw = row.get('QTD_CAIXAS', 0)
                                if pd.isna(qtd_raw) or str(qtd_raw).strip() == "": continue
                                try:
                                    qtd_caixas = int(float(qtd_raw))
                                    if qtd_caixas <= 0: continue
                                except:
                                    continue
                                
                                margem_alvo_lote = row.get('MARGEM_ALVO_PCT', None)
                                preco_negociado_lote = row.get('PRECO_NEGOCIADO', None)
                                
                                pct_descarga_lote = float(row.get('DESCARGA_PCT', 0.0) if pd.notna(row.get('DESCARGA_PCT')) else 0.0)
                                pct_op_logistico_lote = float(row.get('OP_LOGISTICO_PCT', 5.0) if pd.notna(row.get('OP_LOGISTICO_PCT')) else 5.0)
                                pct_comissao_lote = float(row.get('COMISSAO_PCT', 0.0) if pd.notna(row.get('COMISSAO_PCT')) else 0.0)
                                pct_outros_lote = float(row.get('OUTROS_PCT', 0.0) if pd.notna(row.get('OUTROS_PCT')) else 0.0)
                                
                                aliq_icms = p_icms / 100.0
                                aliq_pis_cofins = (p_pis + p_cofins) / 100.0
                                pis_cofins_efetivo = (1 - aliq_icms) * aliq_pis_cofins
                                fot_efetivo = ((FOT_BASE - p_icms) * FOT_ALIQ) / 10000.0
                                st_efetivo = p_st / 100.0
                                desp_operacionais_efetivas = (pct_descarga_lote + pct_op_logistico_lote + pct_comissao_lote + pct_outros_lote) / 100.0
                                
                                aliq_totais_sem_st = aliq_icms + pis_cofins_efetivo + fot_efetivo + desp_operacionais_efetivas
                                
                                preco_final_aplicado = 0.0
                                tipo_preco_aplicado = ""
                                
                                if pd.notna(margem_alvo_lote) and margem_alvo_lote > 0:
                                    denominador = 1 - (aliq_totais_sem_st + (margem_alvo_lote/100.0))
                                    if denominador > 0 and p_custo > 0:
                                        preco_sem_st_alvo = p_custo / denominador
                                        preco_final_aplicado = preco_sem_st_alvo * (1 + st_efetivo)
                                        tipo_preco_aplicado = "Sugerido (Lote)"
                                
                                if preco_final_aplicado == 0.0 and pd.notna(preco_negociado_lote) and preco_negociado_lote > 0:
                                    preco_final_aplicado = float(preco_negociado_lote)
                                    tipo_preco_aplicado = "Negociado (Lote)"
                                    
                                if preco_final_aplicado == 0.0:
                                    preco_final_aplicado = p_preco_atual
                                    tipo_preco_aplicado = "Atual (Lote)"

                                preco_sem_st = preco_final_aplicado / (1 + st_efetivo)
                                vlr_icms = preco_sem_st * aliq_icms
                                base_pis_cofins = preco_sem_st - vlr_icms
                                vlr_pis = base_pis_cofins * (p_pis / 100.0)
                                vlr_cofins = base_pis_cofins * (p_cofins / 100.0)
                                vlr_fot = ((preco_sem_st * (FOT_BASE / 100.0)) - vlr_icms) * (FOT_ALIQ / 100.0)
                                vlr_st = preco_sem_st * st_efetivo
                                
                                impostos_totais_sem_st = vlr_icms + vlr_pis + vlr_cofins + vlr_fot
                                
                                vlr_descarga = preco_sem_st * (pct_descarga_lote / 100.0)
                                vlr_op_log = preco_sem_st * (pct_op_logistico_lote / 100.0)
                                vlr_comissao = preco_sem_st * (pct_comissao_lote / 100.0)
                                vlr_outros = preco_sem_st * (pct_outros_lote / 100.0)
                                despesas_rs = vlr_descarga + vlr_op_log + vlr_comissao + vlr_outros
                                
                                cmv_unit = p_custo + impostos_totais_sem_st + despesas_rs
                                lucro_un = preco_sem_st - cmv_unit
                                margem_un = (lucro_un / preco_sem_st) * 100.0 if preco_sem_st > 0 else 0
                                
                                total_unidades = qtd_caixas * p_qtd_cx
                                custo_aquisicao = p_custo * total_unidades
                                cmv_total = custo_aquisicao + (impostos_totais_sem_st * total_unidades) + (despesas_rs * total_unidades)
                                
                                novo_item_lote = {
                                    "Código": cod, "Produto": p_desc, "Marca": p_marca, "EAN": p_ean,
                                    "Caixas": qtd_caixas, "Unid/CX": p_qtd_cx,
                                    "Total Unid": total_unidades, "Preço Unit.": preco_final_aplicado,
                                    "Preço Sem ST": preco_sem_st,
                                    "Faturamento Total": preco_final_aplicado * total_unidades, "Custo de Aquisição": custo_aquisicao,
                                    "ICMS": vlr_icms * total_unidades, "PIS/COFINS": (vlr_pis + vlr_cofins) * total_unidades,
                                    "FOT": vlr_fot * total_unidades, "ST": vlr_st * total_unidades,
                                    "Descarga": vlr_descarga * total_unidades, "Op. Logístico": vlr_op_log * total_unidades,
                                    "Comissão": vlr_comissao * total_unidades, "Outros": vlr_outros * total_unidades,
                                    "Custo Total (CMV + Desp)": cmv_total,
                                    "Lucro Líquido": lucro_un * total_unidades, "Margem %": margem_un / 100.0,
                                    "Tipo Preço": tipo_preco_aplicado
                                }
                                
                                item_existente_idx = next((i for (i, d) in enumerate(st.session_state['carrinho_deal']) if d["Código"] == cod), None)
                                if item_existente_idx is not None:
                                    st.session_state['carrinho_deal'][item_existente_idx] = novo_item_lote
                                    itens_atualizados += 1
                                else:
                                    st.session_state['carrinho_deal'].append(novo_item_lote)
                                    itens_adicionados += 1
                                    
                                st.session_state['ultimo_produto_simulado'] = cod
                                    
                    st.success(f"Upload processado! {itens_adicionados} itens novos inseridos e {itens_atualizados} atualizados.")
                    st.rerun()
            except Exception as e:
                st.error(f"Erro ao ler o arquivo: Verifique se as colunas estão corretas. Detalhe: {e}")

    # === RENDERIZAÇÃO DO CARRINHO ===
    if st.session_state['carrinho_deal']:
        st.markdown("---")
        st.subheader("🛒 Pedido Consolidado")
        
        col_vpc, _ = st.columns([1, 3])
        with col_vpc:
            vpc_negociacao = st.number_input("💰 Dedução / Verba Global do Pedido (R$)", value=0.0, step=50.0, help="Valor total negociado em Reais (ex: VPC, devolução, bonificação) que será deduzido diretamente do lucro final do pedido.")
            
        df_carrinho = pd.DataFrame(st.session_state['carrinho_deal'])
        
        fat_total = df_carrinho['Faturamento Total'].sum()
        lucro_bruto_itens = df_carrinho['Lucro Líquido'].sum()
        
        lucro_total = lucro_bruto_itens - vpc_negociacao
        fat_sem_st = fat_total - df_carrinho['ST'].sum()
        margem_ponderada = (lucro_total / fat_sem_st) * 100 if fat_sem_st > 0 else 0
        
        cr1, cr2, cr3, cr4 = st.columns(4)
        cr1.metric("Faturamento do Pedido", f"R$ {fat_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        cr2.metric("VPC / Dedução Global", f"- R$ {vpc_negociacao:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        cr3.metric("Lucro Líquido Final", f"R$ {lucro_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        
        if margem_ponderada >= 5.0:
            cr4.metric("Margem Ponderada Target", f"{margem_ponderada:.2f}%", "Saudável ✅", delta_color="normal")
        else:
            cr4.metric("Margem Ponderada Target", f"{margem_ponderada:.2f}%", "Abaixo do Alvo ❌", delta_color="inverse")
            
        st.dataframe(
            df_carrinho[['Código', 'Produto', 'Marca', 'EAN', 'Caixas', 'Preço Unit.', 'Preço Sem ST', 'Faturamento Total', 'Custo Total (CMV + Desp)', 'Lucro Líquido', 'Margem %']].style.format({
                "Preço Unit.": "R$ {:,.2f}",
                "Preço Sem ST": "R$ {:,.2f}",
                "Faturamento Total": "R$ {:,.2f}",
                "Custo Total (CMV + Desp)": "R$ {:,.2f}",
                "Lucro Líquido": "R$ {:,.2f}",
                "Margem %": "{:.2%}" 
            }),
            use_container_width=True,
            hide_index=True
        )
        
        df_carrinho_export = df_carrinho.copy()
        df_carrinho_export['VPC Global'] = 0.0
        
        totais = pd.DataFrame([{
            'Código': 'TOTAL',
            'Produto': f"{df_carrinho['Código'].nunique()} Itens",
            'Marca': '-',
            'EAN': '-',
            'Caixas': df_carrinho['Caixas'].sum(),
            'Unid/CX': '-',
            'Total Unid': df_carrinho['Total Unid'].sum(),
            'Preço Unit.': '-',
            'Preço Sem ST': '-',
            'Faturamento Total': fat_total,
            'Custo de Aquisição': df_carrinho['Custo de Aquisição'].sum(),
            'ICMS': df_carrinho['ICMS'].sum(),
            'PIS/COFINS': df_carrinho['PIS/COFINS'].sum(),
            'FOT': df_carrinho['FOT'].sum(),
            'ST': df_carrinho['ST'].sum(),
            'Descarga': df_carrinho['Descarga'].sum(),
            'Op. Logístico': df_carrinho['Op. Logístico'].sum(),             
            'Comissão': df_carrinho['Comissão'].sum(),
            'Outros': df_carrinho['Outros'].sum(),           
            'Custo Total (CMV + Desp)': df_carrinho['Custo Total (CMV + Desp)'].sum(),
            'VPC Global': vpc_negociacao,
            'Lucro Líquido': lucro_total,
            'Margem %': margem_ponderada / 100.0,
            'Tipo Preço': '-'
        }])
        
        df_detalhado = pd.concat([df_carrinho_export, totais], ignore_index=True)
        
        cols_order = [
            'Código', 'Produto', 'Marca', 'EAN', 'Caixas', 'Unid/CX', 'Total Unid', 'Preço Unit.', 'Preço Sem ST', 
            'Faturamento Total', 'Custo de Aquisição', 'ICMS', 'PIS/COFINS', 'FOT', 'ST', 
            'Descarga', 'Op. Logístico', 'Comissão', 'Outros', 'Custo Total (CMV + Desp)', 
            'VPC Global', 'Lucro Líquido', 'Margem %', 'Tipo Preço'
        ]
        df_detalhado = df_detalhado[cols_order]
        
        df_cliente = df_detalhado[['Código', 'Produto', 'Marca', 'EAN', 'Caixas', 'Unid/CX', 'Total Unid', 'Preço Unit.', 'Preço Sem ST', 'Faturamento Total']].copy()
        
        def formatar_excel(df_alvo, nome_planilha):
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_alvo.to_excel(writer, index=False, sheet_name=nome_planilha)
                worksheet = writer.sheets[nome_planilha]
                
                formato_moeda = 'R$ #,##0.00'
                formato_percentual = '0.00%'
                
                for row in range(2, len(df_alvo) + 2):
                    for col, nome_coluna in enumerate(df_alvo.columns, start=1):
                        celula = worksheet.cell(row=row, column=col)
                        
                        if nome_coluna == 'EAN':
                            celula.number_format = '@'
                            if pd.notna(celula.value) and str(celula.value).strip() != '-':
                                celula.value = str(celula.value).replace('.0', '').strip()
                                
                        elif isinstance(celula.value, (int, float)):
                            if 'Margem' in nome_coluna:
                                celula.number_format = formato_percentual
                            elif nome_coluna not in ['Caixas', 'Unid/CX', 'Total Unid']:
                                celula.number_format = formato_moeda
                                
                for column_cells in worksheet.columns:
                    length = max(len(str(cell.value or "")) for cell in column_cells)
                    worksheet.column_dimensions[column_cells[0].column_letter].width = length + 2
            return buffer.getvalue()
        
        excel_interno = formatar_excel(df_detalhado, 'DRE_Negociacao')
        excel_cliente = formatar_excel(df_cliente, 'Proposta_Comercial')

        col_act1, col_act2, col_act3, col_act4, col_act5 = st.columns([2, 1, 1, 1.2, 1.2])
        
        with col_act1:
            idx_remover = st.selectbox(
                "Remover item:", options=range(len(st.session_state['carrinho_deal'])),
                format_func=lambda i: f"L{i+1}: {st.session_state['carrinho_deal'][i].get('Produto', 'N/A')}"
            )
        with col_act2:
            st.write("") ; st.write("")
            if st.button("❌ Remover", use_container_width=True):
                st.session_state['carrinho_deal'].pop(idx_remover)
                st.rerun()
        with col_act3:
            st.write("") ; st.write("")
            if st.button("🗑️ Limpar", use_container_width=True):
                st.session_state['carrinho_deal'] = []
                st.rerun()
        with col_act4:
            st.write("") ; st.write("")
            st.download_button("📥 Planilha (Visão Interna)", data=excel_interno, file_name="DRE_Negociacao.xlsx", use_container_width=True)
        with col_act5:
            st.write("") ; st.write("")
            st.download_button("📩 Planilha (Visão Cliente)", data=excel_cliente, file_name="Proposta_Comercial.xlsx", use_container_width=True)

# ==========================================
# TAB 2: DIAGNÓSTICO UNITÁRIO (CASCATA)
# ==========================================
with tab_waterfall:
    st.subheader("📊 Decomposição Financeira Unitária (Waterfall)")
    st.markdown("Visualize o caminho do dinheiro para **uma única unidade** do produto: do preço pago pelo cliente até o lucro real, após impostos e despesas.")

    st.write("**🔍 Busque o Produto:**")
    col_b_wf1, col_b_wf2, col_b_wf3 = st.columns([1, 1, 2])
    
    with col_b_wf1:
        lista_marcas_wf = listar_marcas(df_base)
        marca_selecionada_wf = st.selectbox("Filtro por Marca:", lista_marcas_wf, index=None, placeholder="Todas as marcas...", key="marca_wf")
        
    with col_b_wf2:
        filtro_wf = st.text_input("Filtro Rápido (Texto):", "", key="txt_busca_wf", placeholder="Ex: azeite", help="Digite qualquer parte do nome para filtrar a lista.")
        
    lista_produtos_raw_wf = listar_produtos_dropdown(df_base, marca_selecionada_wf)
    
    if filtro_wf:
        lista_produtos_filtrada_wf = [p for p in lista_produtos_raw_wf if filtro_wf.upper() in p.upper()]
    else:
        lista_produtos_filtrada_wf = lista_produtos_raw_wf
        
    with col_b_wf3:
        produto_wf = st.selectbox("Selecione o Produto para Análise Gráfica:", lista_produtos_filtrada_wf, index=None, placeholder="Selecione um produto...", key="busca_wf_select")

    if produto_wf:
        cod_prod_wf = produto_wf.split(" - ")[0].strip()
        
        try:
            df_prod_wf = buscar_produto(cod_prod_wf, df_base)
            
            if not df_prod_wf.empty and pd.notna(df_prod_wf['DESCRICAO'].iloc[0]):
                p_desc_wf = df_prod_wf['DESCRICAO'].iloc[0]
                p_custo_wf = float(df_prod_wf['CUSTO_ULT_ENT'].iloc[0] or 0.0)
                p_icms_wf = float(df_prod_wf['PERC_ICMS'].iloc[0] or 0.0)
                p_pis_wf = float(df_prod_wf['PERCPIS'].iloc[0] or 0.0)
                p_cofins_wf = float(df_prod_wf['PERCCOFINS'].iloc[0] or 0.0)
                p_st_wf = float(df_prod_wf['PERC_ST'].iloc[0] or 0.0)
                p_preco_atual_wf = float(df_prod_wf['PVENDAST'].iloc[0] or 0.0)
                p_estoque_wf = int(df_prod_wf['ESTOQUE_CX'].iloc[0] or 0)
                
                preco_sem_st_erp = p_preco_atual_wf / (1 + (p_st_wf / 100))
                
                st.markdown(f"""
                <div style="background-color: #2b303b; border-left: 5px solid #00cc96; padding: 15px; border-radius: 5px; color: #ffffff; margin-bottom: 20px;">
                    <h4 style="margin: 0 0 10px 0; color: #ffffff;">{p_desc_wf}</h4>
                    <span style="font-size: 14px;">
                        <b>Custo Unitário (Aquisição):</b> R$ {p_custo_wf:.2f} &nbsp;|&nbsp; 
                        <b>Preço Unit. Tabela (Com ST):</b> R$ {p_preco_atual_wf:.2f} &nbsp;|&nbsp; 
                        <b>Preço Unit. Tabela (Sem ST):</b> R$ {preco_sem_st_erp:.2f} &nbsp;|&nbsp;
                        <b>Estoque Disp.:</b> {p_estoque_wf} Cx
                    </span>
                </div>
                """, unsafe_allow_html=True)
                
                col_cenario1, col_cenario2 = st.columns([1.5, 2])
                
                with col_cenario1:
                    cenario = st.radio("Cenário de Precificação a exibir:", 
                                       ["💰 Preço Tabela (ERP)", "🎯 Margem Alvo (Sugerido)", "🤝 Preço Negociado (Fixo)"])
                    
                with col_cenario2:
                    st.write("**Parâmetros de Preço**")
                    
                    if cenario == "🎯 Margem Alvo (Sugerido)":
                        alvo_wf = st.number_input("Margem Líquida Alvo (%)", value=5.0, step=0.5, key="alvo_wf") / 100.0
                        preco_base_wf = 0.0 
                    elif cenario == "🤝 Preço Negociado (Fixo)":
                        preco_base_wf = st.number_input("Preço Unitário Fechado (R$)", value=p_preco_atual_wf, step=0.5, key="preco_fixo_wf")
                    else:
                        preco_base_wf = p_preco_atual_wf
                        
                with st.expander("⚙️ Ajustar Despesas Operacionais (%)", expanded=False):
                    cd_w1, cd_w2, cd_w3, cd_w4 = st.columns(4)
                    pct_f_wf = cd_w1.number_input("Descarga (%)", value=0.0, step=0.5, key="fwf_wf_2")
                    pct_fi_wf = cd_w2.number_input("Op. Logístico (%)", value=5.0, step=0.5, key="fiwf_wf_2")
                    pct_c_wf = cd_w3.number_input("Comissão (%)", value=0.0, step=0.5, key="cwf_wf_2")
                    pct_o_wf = cd_w4.number_input("Outros (%)", value=0.0, step=0.5, key="owf_wf_2")
                
                aliq_icms_wf = p_icms_wf / 100.0
                aliq_pis_cofins_wf = (p_pis_wf + p_cofins_wf) / 100.0
                pis_cofins_efetivo_wf = (1 - aliq_icms_wf) * aliq_pis_cofins_wf
                fot_efetivo_wf = ((22.0 - p_icms_wf) * 18.18) / 10000.0
                st_efetivo_wf = p_st_wf / 100.0
                desp_op_wf = (pct_f_wf + pct_fi_wf + pct_c_wf + pct_o_wf) / 100.0
                
                if cenario == "🎯 Margem Alvo (Sugerido)":
                    denominador_wf = 1 - (aliq_icms_wf + pis_cofins_efetivo_wf + fot_efetivo_wf + desp_op_wf + alvo_wf)
                    if denominador_wf > 0 and p_custo_wf > 0:
                        preco_sem_st_wf = p_custo_wf / denominador_wf
                        preco_base_wf = preco_sem_st_wf * (1 + st_efetivo_wf)
                    else:
                        st.error("Custos ultrapassam o preço. Margem inviável.")
                        preco_base_wf = p_preco_atual_wf
                        preco_sem_st_wf = preco_base_wf / (1 + st_efetivo_wf)
                else:
                    preco_sem_st_wf = preco_base_wf / (1 + st_efetivo_wf)
                        
                vlr_icms_wf = preco_sem_st_wf * aliq_icms_wf
                base_pis_cofins_wf = preco_sem_st_wf - vlr_icms_wf
                vlr_pis_wf = base_pis_cofins_wf * (p_pis_wf / 100.0)
                vlr_cofins_wf = base_pis_cofins_wf * (p_cofins_wf / 100.0)
                vlr_fot_wf = ((preco_sem_st_wf * 0.22) - vlr_icms_wf) * 0.1818
                vlr_st_wf = preco_sem_st_wf * st_efetivo_wf
                
                impostos_unit = vlr_icms_wf + vlr_pis_wf + vlr_cofins_wf + vlr_fot_wf + vlr_st_wf
                
                vlr_descarga_wf = preco_sem_st_wf * (pct_f_wf / 100.0)
                vlr_op_log_wf = preco_sem_st_wf * (pct_fi_wf / 100.0)
                vlr_comissao_wf = preco_sem_st_wf * (pct_c_wf / 100.0)
                vlr_outros_wf = preco_sem_st_wf * (pct_o_wf / 100.0)
                despesas_unit = vlr_descarga_wf + vlr_op_log_wf + vlr_comissao_wf + vlr_outros_wf
                
                lucro_unit_real = preco_sem_st_wf - p_custo_wf - (impostos_unit - vlr_st_wf) - despesas_unit
                margem_wf_final = (lucro_unit_real / preco_sem_st_wf) * 100 if preco_sem_st_wf > 0 else 0

                st.markdown("---")
                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("Preço Unit. Final", f"R$ {preco_base_wf:.2f}")
                k2.metric("Impostos Unit.", f"R$ {impostos_unit:.2f}")
                k3.metric("Despesas Unit.", f"R$ {despesas_unit:.2f}")
                k4.metric("Lucro Líquido Unit.", f"R$ {lucro_unit_real:.2f}")
                
                if margem_wf_final >= 5.0:
                    k5.metric("Margem Real Unit. (%)", f"{margem_wf_final:.2f}%", "Aprovada ✅", delta_color="normal")
                elif margem_wf_final > 0:
                    k5.metric("Margem Real Unit. (%)", f"{margem_wf_final:.2f}%", "Alerta 🟡", delta_color="off")
                else:
                    k5.metric("Margem Real Unit. (%)", f"{margem_wf_final:.2f}%", "Prejuízo ❌", delta_color="inverse")

                eixo_x = ["1. Preço Final", "2. Impostos Totais", "3. Custo Produto", "4. Despesas Comerciais", "5. Lucro Líquido Real"]
                text_grafico = [f"R$ {preco_base_wf:.2f}", f"-R$ {impostos_unit:.2f}", f"-R$ {p_custo_wf:.2f}", f"-R$ {despesas_unit:.2f}", f"R$ {lucro_unit_real:.2f}"]
                y_grafico = [preco_base_wf, -impostos_unit, -p_custo_wf, -despesas_unit, lucro_unit_real]
                
                medidas_grafico = ["relative", "relative", "relative", "relative", "total"]

                fig_waterfall = go.Figure(go.Waterfall(
                    name="Formação de Preço Unitária", orientation="v",
                    measure=medidas_grafico,
                    x=eixo_x,
                    textposition="outside",
                    text=text_grafico,
                    y=y_grafico,
                    connector={"line": {"color": "rgba(255, 255, 255, 0.2)"}},
                    decreasing={"marker": {"color": "#ef553b"}},
                    increasing={"marker": {"color": "#00cc96"}},
                    totals={"marker": {"color": "#636efa" if lucro_unit_real >= 0 else "#ef553b"}},
                    hovertemplate="<b>%{x}</b><br>Impacto: %{text}<extra></extra>"
                ))
                
                fig_waterfall.update_layout(
                    title=f"Decomposição de Margem Unitária: {p_desc_wf}",
                    plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                    height=550, margin=dict(l=20, r=20, t=50, b=20),
                    yaxis=dict(title="Valor em Reais (R$)")
                )
                
                st.plotly_chart(fig_waterfall, use_container_width=True)
                
                st.markdown("### 🔍 Detalhamento Financeiro (Por Unidade)")
                
                linhas_detalhe = [
                    {"Componente": "Preço Unitário (Final)", "Valor (R$)": preco_base_wf, "Representação (%)": 100.0},
                    {"Componente": "(-) ICMS", "Valor (R$)": vlr_icms_wf, "Representação (%)": (vlr_icms_wf/preco_base_wf)*100 if preco_base_wf else 0},
                    {"Componente": "(-) PIS/COFINS", "Valor (R$)": (vlr_pis_wf + vlr_cofins_wf), "Representação (%)": ((vlr_pis_wf + vlr_cofins_wf)/preco_base_wf)*100 if preco_base_wf else 0},
                    {"Componente": "(-) FOT", "Valor (R$)": vlr_fot_wf, "Representação (%)": (vlr_fot_wf/preco_base_wf)*100 if preco_base_wf else 0},
                    {"Componente": "(-) ST (Substituição Tributária)", "Valor (R$)": vlr_st_wf, "Representação (%)": (vlr_st_wf/preco_base_wf)*100 if preco_base_wf else 0},
                    {"Componente": "(=) TRIBUTOS TOTAIS", "Valor (R$)": impostos_unit, "Representação (%)": (impostos_unit/preco_base_wf)*100 if preco_base_wf else 0},
                    {"Componente": "(-) Custo da Mercadoria (Base)", "Valor (R$)": p_custo_wf, "Representação (%)": (p_custo_wf/preco_base_wf)*100 if preco_base_wf else 0},
                    {"Componente": "(-) Descarga", "Valor (R$)": vlr_descarga_wf, "Representação (%)": pct_f_wf},
                    {"Componente": "(-) Op. Logístico", "Valor (R$)": vlr_op_log_wf, "Representação (%)": pct_fi_wf},
                    {"Componente": "(-) Comissão", "Valor (R$)": vlr_comissao_wf, "Representação (%)": pct_c_wf},
                    {"Componente": "(-) Outros", "Valor (R$)": vlr_outros_wf, "Representação (%)": pct_o_wf},
                    {"Componente": "(=) DESPESAS TOTAIS", "Valor (R$)": despesas_unit, "Representação (%)": desp_op_wf*100},
                    {"Componente": "(=) LUCRO LÍQUIDO REAL", "Valor (R$)": lucro_unit_real, "Representação (%)": margem_wf_final}
                ]

                df_detalhe = pd.DataFrame(linhas_detalhe)
                
                st.dataframe(
                    df_detalhe.style.format({
                        "Valor (R$)": "R$ {:,.2f}",
                        "Representação (%)": "{:.2f}%"
                    }).apply(lambda x: ['background-color: rgba(255,255,255,0.05); font-weight: bold' if '(=)' in str(v) else '' for v in x], axis=1),
                    use_container_width=True,
                    hide_index=True
                )
                
        except Exception as e:
            st.error(f"Erro ao gerar gráfico e tabela: {e}")
