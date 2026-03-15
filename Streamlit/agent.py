import pandas as pd
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

# --- [1. 설정 및 DB 연결] ---
SUPABASE_URL = "https://ekkpnjfybpodkrvcugpr.supabase.co"
SUPABASE_KEY = "sb_publishable_Z2Dogn7vCkA0szrRR-LuwQ_Po18uuZ8"
GEMINI_API_KEY = "AIzaSyDXNUHEoMoTqcyxwNq90MbrnWfVNu-OCF8"


supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- [2. RAG용 통합 데이터 추출 함수] ---
# get_unified_data가 없다고 하셨으므로, 에이전트용으로 새로 구축했습니다.
def fetch_full_shop_data():
    """DB의 여러 테이블을 읽어와서 에이전트가 읽기 좋은 하나의 텍스트로 합칩니다."""
    
    # A. 재고 및 품목 정보 (STOCKS + ITEMS)
    res_s = supabase.table("STOCKS").select("*, ITEMS(name, category)").execute()
    df_s = pd.DataFrame(res_s.data)
    
    # B. 공급처 및 단가 정보 (SUPPLIER_DETAILS)
    res_d = supabase.table("SUPPLIER_DETAILS").select("*, SUPPLIERS(name)").eq("status", True).execute()
    df_d = pd.DataFrame(res_d.data)
    
    # C. 최근 실사 로그 (STOCK_LOGS)
    res_l = supabase.table("STOCK_LOGS").select("*, ITEMS(name)").order("last_checked_at", desc=True).limit(20).execute()
    df_l = pd.DataFrame(res_l.data)

    # 데이터 정리 및 병합
    if not df_s.empty and not df_d.empty:
        df_s['item_name'] = df_s['ITEMS'].apply(lambda x: x.get('name') if isinstance(x, dict) else "N/A")
        df_d['sup_name'] = df_d['SUPPLIERS'].apply(lambda x: x.get('name') if isinstance(x, dict) else "N/A")
        
        # 현재고 현황판 제작
        inv_merged = pd.merge(df_s, df_d, on=['item_id', 'supplier_id'], how='left')
        inventory_text = inv_merged[['category', 'item_name', 'sup_name', 'stock', 'avg_consumption', 'safety_stock', 'order_unit_price']].to_markdown(index=False)
    else:
        inventory_text = "현재 재고 데이터가 비어있습니다."

    if not df_l.empty:
        df_l['item_name'] = df_l['ITEMS'].apply(lambda x: x.get('name') if isinstance(x, dict) else "N/A")
        # 오차율(error_rate) 포함 로그판 제작
        log_text = df_l[['item_name', 'exp_stock', 'act_stock', 'error', 'error_rate', 'last_checked_at']].to_markdown(index=False)
    else:
        log_text = "최근 실사 로그가 없습니다."

    return f"### [매장 실시간 재고 및 단가 현황]\n{inventory_text}\n\n### [최근 20건의 실사 및 오차 기록]\n{log_text}"

# --- [3. 에이전트 도구 정의] ---
@tool
def get_cafe_context():
    """매장의 재고, 공급처, 오차율 등 모든 데이터를 한꺼번에 가져옵니다. 
    사장님의 질문에 답하기 위해 가장 먼저 이 도구를 실행하여 현황을 파악하세요."""
    return fetch_full_shop_data()

# --- [4. 최신 표준 에이전트 구축] ---
# 1.5-flash-latest를 사용하여 긴 문맥(RAG 데이터)을 저렴하고 빠르게 처리합니다.
llm = ChatGoogleGenerativeAI(model="gemini-flash-latest", google_api_key=GEMINI_API_KEY)

# 시스템 프롬프트: '알아서 판단하라'는 지침을 강하게 줍니다.
system_prompt = """
당신은 카페 재고 관리의 '마스터 참모'입니다. 
사장님이 세세한 상황을 설명하지 않아도, 'get_cafe_context'를 통해 얻은 데이터를 보고 스스로 추론하세요.

분석 가이드:
- **재고 부족**: 현재고(stock)가 안전재고(safety_stock)보다 적으면 즉시 경고하세요.
- **오차 추적**: 로그의 'error_rate'가 유독 높은 품목은 사장님께 실사 주의를 당부하세요.
- **발주 제언**: 소모 속도(avg_consumption)를 고려해 며칠 뒤에 재고가 바닥날지 예측하고 발주 리스트를 짜주세요.
- **유연성**: 데이터 간의 상관관계를 파악하여 사장님이 묻지 않은 잠재적 리스크까지 먼저 언급하세요.
"""

app = create_agent(llm, tools=[get_cafe_context], system_prompt=system_prompt,)

# --- [5. 테스트 실행 함수] ---
def run_agent_test(user_input: str):
    print(f"\n💬 사장님: {user_input}")
    inputs = {"messages": [HumanMessage(content=user_input)]}
    
    # 에이전트 실행 및 스트리밍 결과 출력
    for s in app.stream(inputs, stream_mode="values"):
        message = s["messages"][-1]
    
    print(f"\n🤖 에이전트:\n{message.content}")

if __name__ == "__main__":
    # 테스트 시나리오
    run_agent_test("지금 우리 매장에서 데이터적으로 가장 이상한 점이 뭐야? 재고랑 오차율 다 보고 말해줘.")