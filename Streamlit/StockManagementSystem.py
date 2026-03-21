import streamlit as st
from Utilities.Styles import apply_custom_css
from Componenets.DashboardPage import render_dashboard
from Componenets.InventoryCountPage import render_inventorycount
from Componenets.OrderPage import render_order
from Componenets.AdminPage import render_admin
from Componenets.AIAgentPage import render_agent

st.set_page_config(page_title="만월경 통합 관리", layout="wide")

# CSS. 버튼색상 및 폰트크기 설정
apply_custom_css()

# 상단 메뉴 구성 (Tabs)
tab_dash, tab_order, tab_check, tab_admin, tab_chat = st.tabs(["실시간 대시보드", "발주 관리", "재고 실사", "마스터 관리창", "AI 에이전트"])

# -------------------------------------------------------------------------------------------
# 메뉴 1: 실시간 대시보드 & 입고 기능(DashboardPage.py)
# -------------------------------------------------------------------------------------------
with tab_dash: render_dashboard()

# -------------------------------------------------------------------------------------------
# 메뉴 2: 발주 관리(OrderPage.py)
# -------------------------------------------------------------------------------------------
with tab_order: render_order()

# -------------------------------------------------------------------------------------------
# 메뉴 3: 재고 실사(InventoryCountPage.py)
# -------------------------------------------------------------------------------------------
with tab_check: render_inventorycount()

# -------------------------------------------------------------------------------------------
# 메뉴 4: 마스터 관리창 (AdminPage.py)
# -------------------------------------------------------------------------------------------
with tab_admin: render_admin()

# -------------------------------------------------------------------------------------------
# 메뉴 5: 재고 AI 에이전트 (AgentPage.py)
# -------------------------------------------------------------------------------------------
with tab_chat: render_agent()