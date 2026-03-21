import streamlit as st
import pandas as pd
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from langchain_core.tools import tool
from Database import supabase, get_unified_inventory_data
from langchain_core.messages import HumanMessage

def ask_agent(user_prompt):
    """
    사용자의 질문을 받아 에이전트를 실행하고 최종 답변(문자열)만 반환합니다.
    """
    # 1. 랭체인 메시지 형식으로 변환
    inputs = {"messages": [HumanMessage(content=user_prompt)]}
    config = {"configurable": {"thread_id": "cafe_session"}}
    
    # 2. 에이전트 실행 및 결과 추출
    response = agent_executor.invoke(inputs, config=config)
    last_msg = response["messages"][-1]

    # 3. 복잡한 응답 구조에서 텍스트만 추출 (다이어트 로직)
    if isinstance(last_msg.content, list):
        final_answer = last_msg.content[0].get('text', str(last_msg.content))
    else:
        final_answer = last_msg.content
        
    return final_answer



# LLM 정의
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite", 
    google_api_key=st.secrets["GEMINI_API_KEY"],
    temperature=0
)

@tool
def get_cafe_inventory_context():
    """매장의 전체 재고 현황 및 최근 오차율 로그 통합 조회"""
    inventory_df = get_unified_inventory_data()
    
    # 최근 45건 로그 로드
    log_res = supabase.table("STOCK_LOGS").select("*, ITEMS(name)").order("last_checked_at", desc=True).limit(45).execute()
    df_log = pd.DataFrame(log_res.data)
    
    #AI의 가독성을 위해 딕셔너리>리스트로 형태 변환
    if not df_log.empty:
        df_log['item_name'] = df_log['ITEMS'].apply(lambda x: x.get('name', 'N/A'))
        df_log = df_log[['item_name', 'exp_stock', 'act_stock', 'error', 'error_rate', 'last_checked_at']]

    context = "## [실시간 재고 정보]\n" + inventory_df[['category', 'item_name', 'stock', 'avg_consumption', 'safety_stock', 'order_unit_price']].to_markdown(index=False)
    context += "\n\n## [최근 45건 로그]\n" + df_log.to_markdown(index=False)
    return context

#에이전트 프롬프트
system_msg = """당신은 카페 '만월경'의 재고 관리자입니다. 
데이터를 기반으로 논리적으로 추론하고, 사장님이 묻지 않아도 잠재적 리스크를 먼저 짚어주세요. 판매중단된 품목은 제외하세요.
- 재고 부족: stock < safety_stock 일 때 우선 보고
- 오차 분석: error_rate가 높은 품목은 실사 신뢰도 문제 제기
- 제안: 사장님이 효율적인 의사결정을 할 수 있도록 결론부터 말하세요."""

#직접 호출하는 대신 캐싱으로 처리
@st.cache_resource
def get_cached_agent():
    return create_agent(llm, tools=[get_cafe_inventory_context], system_prompt=system_msg)

agent_executor = get_cached_agent()


