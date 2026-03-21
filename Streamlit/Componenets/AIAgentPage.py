import streamlit as st
from Utilities.AIAgent import ask_agent

def render_agent():
    st.title("AI 에이전트")
    st.caption("매장 데이터를 분석하여 재고 관리 전략을 제안합니다.")

    # 세션 상태로 대화 기록 유지
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # 채팅 메시지 출력
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # 채팅 입력창
    if prompt := st.chat_input("예: 최근 오차가 심한 품목은 뭐야?"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("데이터 분석 및 보고서 작성 중..."):
                #AIAgent.py 함수 호출
                final_answer = ask_agent(prompt)
                st.markdown(final_answer)
                
        # 답변을 세션 상태에 저장
        st.session_state.messages.append({"role": "assistant", "content": final_answer})