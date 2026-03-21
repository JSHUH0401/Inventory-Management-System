import streamlit as st
import pandas as pd
from supabase import create_client

# DB 키, 정보 불러오기
URL = st.secrets["SUPABASE_URL"]
KEY = st.secrets["SUPABASE_KEY"]

@st.cache_resource
def init_connection():
    return create_client(URL, KEY)
supabase = init_connection()

@st.cache_data(ttl=600)
def get_unified_inventory_data():
    """재고, 품목, 공급처 정보를 통합하여 반환"""
    # 1. 재고 및 품목 기본 정보 로드
    stocks_response = supabase.table("STOCKS").select("*, ITEMS(name, category)").execute()
    stocks_df = pd.DataFrame(stocks_response.data)
    
    if stocks_df.empty: return pd.DataFrame()

    stocks_df['item_name'] = stocks_df['ITEMS'].apply(lambda x: x.get('name', 'N/A'))
    stocks_df['category'] = stocks_df['ITEMS'].apply(lambda x: x.get('category', '기타'))
    
    # 2. 공급처 상세 정보 로드
    details_response = supabase.table("SUPPLIER_DETAILS").select("*").eq("status", True).execute()
    details_df = pd.DataFrame(details_response.data)

    # 3. 데이터 병합
    unified_df = pd.merge(stocks_df, details_df, on=['item_id', 'supplier_id'], how='left')
    return unified_df.loc[:, ~unified_df.columns.duplicated()]