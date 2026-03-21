import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
from Utilities.Database import supabase, get_unified_inventory_data
from Utilities.StockCalculation import get_total_weight
def render_dashboard():
    KST = timezone(timedelta(hours=9)) # 한국 표준시 설정, Supabase에서 한국 기준시 제공을 안 함.
    st.title("실시간 재고 모니터링")
    df = get_unified_inventory_data()
    now_kst = datetime.now(KST)
    res_logs = supabase.table("STOCK_LOGS").select("*, ITEMS(name)").order("last_checked_at", desc=True).limit(30).execute()
    system_accuracy = 0.0 # 기본값

    if res_logs.data:
        df_logs = pd.DataFrame(res_logs.data)
        
        # 예측 재고가 0인 경우(신규 품목 등)를 제외하여 정확도 왜곡 방지
        valid_logs = df_logs[df_logs['exp_stock'] > 0].copy()
        
        if not valid_logs.empty:
            total_exp = valid_logs['exp_stock'].sum()
            total_abs_error = valid_logs['error'].abs().sum()
            # IRA 방식 정확도 계산
            system_accuracy = max(0, 100 - (total_abs_error / total_exp * 100))

    predicted_list = []
    for _, row in df.iterrows():
        lc = pd.to_datetime(row['last_checked_at']).tz_convert('Asia/Seoul')
        pred = max(0, row['stock'] - (row['avg_consumption'] * get_total_weight(lc, now_kst)))
        predicted_list.append({**row, "예측재고": round(pred, 2)})

    res_df = pd.DataFrame(predicted_list)
    danger = res_df[res_df['예측재고'] < res_df['safety_stock']]

    c1, c2, c3 = st.columns(3)
    c1.metric("전체 품목", len(res_df))
    c2.metric("발주 필요", len(danger), delta_color="inverse")

    # 위에서 계산된 정확도 표시
    if not df_logs.empty:
        c3.metric("시스템 재고 정확도", f"{system_accuracy:.1f}%")
    else:
        c3.metric("시스템 재고 정확도", "데이터 없음")

    if not danger.empty:
        st.subheader("안전재고 미달 품목")
        st.dataframe(danger[['category', 'item_name', '예측재고', 'safety_stock', 'base_unit']], use_container_width=True, hide_index=True)

    # 최근 소진속도 급증 품목
    st.divider()
    st.subheader("소진속도 급증 품목 (Top 5)")
    # STOCK_LOGS에서 최신 로그 데이터 가져오기
    if res_logs.data:
        df_logs = pd.DataFrame(res_logs.data)
        # 조인된 데이터에서 품목명 추출
        df_logs['item_name'] = df_logs['ITEMS'].apply(lambda x: x.get('name') if isinstance(x, dict) else "N/A")
        
        # 속도 변화 비율 계산 (새 소모율 / 이전 소모율)
        # 0으로 나누는 에러를 방지하기 위해 old_avg_consumption이 0보다 큰 경우만 계산
        df_logs['speed_ratio'] = df_logs.apply(
            lambda x: (x['new_avg_consumption'] / x['old_avg_consumption']) if x['old_avg_consumption'] > 0 else 1.0, 
            axis=1
        )
        
        # 속도가 빨라진(비율 > 1.0) 품목 중 중복을 제거하고 최신 기록 기준으로 상위 5개 추출
        # 같은 품목이 여러 번 있을 경우 가장 최근(상단) 것만 남김
        fast_df = df_logs.drop_duplicates(subset=['item_id']).sort_values(by='speed_ratio', ascending=False).head(5)      

        if not fast_df.empty:
            # 증가율 퍼센트 계산
            fast_df['increase_pct'] = ((fast_df['speed_ratio'] - 1) * 100).round(1)
            
            for _, row in fast_df.iterrows():
                with st.container(border=True):
                    c1, c2 = st.columns([1, 4])
                    c1.markdown(f"### {row['increase_pct']}%")
                    c2.markdown(f"**{row['item_name']}**의 소모 속도가 평소보다 빨라졌습니다.  \n"
                                f"현재 속도: 하루 {row['new_avg_consumption']:.2f}개 (기존: {row['old_avg_consumption']:.2f}개)")
        else:
            st.success("✅ 현재 소모 속도가 급격히 빨라진 품목이 없습니다. 평화로운 상태입니다.")
    else:
        st.info("💡 분석을 위한 로그 데이터가 아직 없습니다. '재고 실사'를 진행하면 데이터가 쌓이기 시작합니다.")

    st.divider()
    st.subheader("배송 중인 주문 및 입고 처리")
    # 배송 현황 로드
    res_o = supabase.table("PURCHASE_ORDERS").select("*, SUPPLIERS(name)").eq("status", "배송중").execute()
    orders = pd.DataFrame(res_o.data)

    if orders.empty: 
        st.info("배송 중인 내역이 없습니다.")
    else:
        for _, order in orders.iterrows():
            oid = order['order_id']
            col_info, col_btn = st.columns([5, 1])
            
            with col_info:
                # 1. expander 선언 (주문별로 하나씩)
                exp = st.expander(f"📦 주문 {order['SUPPLIERS']['name']} (결제액: {order['total_price']:,}원)")
                
                # 2. expander 내부에 상세 품목 표시
                with exp:
                    items_res = supabase.table("PURCHASE_ITEMS").select("*, ITEMS(name)").eq("order_id", oid).execute()
                    if items_res.data:
                        for itm in items_res.data:
                            item_name = itm['ITEMS']['name']
                            qty = itm['actual_qty']
                            st.write(f"- {item_name}: **{qty}** 개")
                    else:
                        st.write("상세 품목 정보가 없습니다.")
            
            with col_btn:
                # 버튼 위치 조정 여백
                st.write("<div style='height: 5px;'></div>", unsafe_allow_html=True)
                
                # 고유한 key 설정
                if st.button("입고완료", key=f"rec_{oid}", use_container_width=True):
                    # 입고 처리 로직
                    items_res = supabase.table("PURCHASE_ITEMS").select("*").eq("order_id", oid).execute()
                    for itm in items_res.data:
                        details = supabase.table("SUPPLIER_DETAILS").select("conversion_factor").match({"item_id": itm['item_id'], "supplier_id": order['supplier_id']}).execute()
                        cf = details.data[0]['conversion_factor'] if details.data else 1
                        inc_qty = itm['actual_qty'] * cf
                        
                        # 현재 재고 가져오기 및 업데이트
                        stock_data = supabase.table("STOCKS").select("stock").match({"item_id": itm['item_id'], "supplier_id": order['supplier_id']}).execute().data
                        if stock_data:
                            curr_stock = stock_data[0]['stock']
                            supabase.table("STOCKS").update({"stock": float(curr_stock + inc_qty)}).match({"item_id": itm['item_id'], "supplier_id": order['supplier_id']}).execute()
                    
                    # 상태 업데이트 및 새로고침
                    supabase.table("PURCHASE_ORDERS").update({"status": "입고완료"}).eq("order_id", oid).execute()
                    st.cache_data.clear() #입고됐으니 캐시 초기화
