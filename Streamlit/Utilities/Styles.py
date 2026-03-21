import streamlit as st

### 시스템 글자 폰트색상 및 크기 설정 ###


def apply_custom_css():
    # CSS. 버튼색상 및 폰트크기 설정
    st.markdown("""
        <style>
        /* 1. 최상단 메인 제목 (st.title) 스타일 */
        .stApp h1 {
            font-size: 28px !important;
            font-weight: 700 !important;
            padding-top: 0px !important;
            padding-bottom: 15px !important;
        }
        /* 상단 탭 메뉴(실시간 대시보드, 발주 관리 등)의 글자 크기 조절 */
        .stTabs [data-baseweb="tab"] p {
            font-size: 18px !important;  /* 기존보다 크게 20px로 설정 */
        }
        /* Primary 버튼 색상을 강렬한 빨간색에서 차분한 네이비 블루로 변경 */
        div.stButton > button[kind="primary"] {
            background-color: #2E4053; 
            color: white;
            border-color: #2E4053;
        }
        div.stButton > button[kind="primary"]:hover {
            background-color: #1B2631;
            border-color: #1B2631;
        }
        /* 수량 조절 버튼 크기 미세 조정 */
        .stButton button { font-size: 12px; padding: 2px 5px; }
        </style>
        """, unsafe_allow_html=True)
