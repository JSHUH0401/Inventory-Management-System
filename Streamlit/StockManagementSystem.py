import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
from Database import supabase, get_unified_inventory_data
from AIAgent import ask_agent
from StockCalculation import get_total_weight

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


# 상단 메뉴 구성 (Tabs)
st.set_page_config(page_title="만월경 통합 관리", layout="wide")
tab_dash, tab_order, tab_check, tab_admin, tab_chat = st.tabs(["실시간 대시보드", "발주 관리", "재고 실사", "마스터 관리창", "AI 에이전트"])
# -------------------------------------------------------------------------------------------
# 메뉴 1: 실시간 대시보드 & 입고 기능
# -------------------------------------------------------------------------------------------
KST = timezone(timedelta(hours=9)) # 한국 표준시 설정, Supabase에서 한국 기준시 제공을 안 함.
with tab_dash:
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

# -------------------------------------------------------------------------------------------
# 메뉴 2: 발주 관리
# -------------------------------------------------------------------------------------------
with tab_order:
    # 앱 최상단에 알림 영역 추가
    if 'show_toast' not in st.session_state:
        st.session_state.show_toast = False

    # 발주 완료 메시지 출력
    if st.session_state.show_toast:
        st.toast("발주 완료 처리되었습니다.")
        st.session_state.show_toast = False # 메시지를 한 번 보여준 후 다시 꺼줌

    #########################################################################

    # 초기 데이터 호출 함수
    @st.cache_data
    def load_data():
        # ITEMS를 가져오면서 연결된 상세정보와 재고를 한꺼번에 가져옴
        query = """
            id, name,
            SUPPLIER_DETAILS (
                supplier_id, order_url, MOQ, safety_stock, order_unit_price,status,
                SUPPLIERS ( name )
            ),
            STOCKS ( stock, supplier_id )
        """
        response = supabase.table("ITEMS").select(query).execute()
        if not response.data:
            return []

        filtered_data = []
        for item in response.data:
            # 판매 중인 아이템(status == True)인 것만 가져옴
            active_details = [
                sd for sd in item.get("SUPPLIER_DETAILS", []) 
                if sd.get("status") == True
            ]
            
            # 판매 중인 공급처 상세 정보가 있는 경우에만 최종 리스트에 추가
            if active_details:
                item["SUPPLIER_DETAILS"] = active_details
                
                # 해당 공급처의 재고 데이터만 남기기(필요없는 데이터들은 최대한 배제)
                active_sup_ids = [sd["supplier_id"] for sd in active_details]
                item["STOCKS"] = [
                    s for s in item.get("STOCKS", []) 
                    if s["supplier_id"] in active_sup_ids
                ]
                
                filtered_data.append(item)
        return filtered_data

    if 'item_master' not in st.session_state:
        st.session_state.item_master = load_data()

    ###############################################################################################

    # 상태 관리 변수(모드 기억용)
    if 'order_mode' not in st.session_state:
        st.session_state.order_mode = "추천"
    if 'manual_cart' not in st.session_state:
        st.session_state.manual_cart = {}

    
    def order_page():
        st.title("만월경 발주 관리")
        # 발주 모드 선택 영역
        st.write("### 📂 발주 모드 선택")
        col_rec, col_cus = st.columns(2)
        
        with col_rec:
            rec_style = "primary" if st.session_state.order_mode == "추천" else "secondary"
            if st.button("시스템 추천 발주", use_container_width=True, type=rec_style):
                st.session_state.order_mode = "추천"
                st.session_state.manual_cart = {}

        with col_cus:
            cus_style = "primary" if st.session_state.order_mode == "커스텀" else "secondary"
            if st.button("커스텀 발주", use_container_width=True, type=cus_style):
                st.session_state.order_mode = "커스텀"
                st.session_state.manual_cart = {}

        # 품목 직접 추가 영역(발주 아이템 직접 추가)
        with st.container(border=True):
            st.subheader("품목 직접 추가")
            c1, c2, c3 = st.columns([4, 4, 1.5])
            
            # item_names 가져오기
            item_names = [i["name"] for i in st.session_state.item_master]
            sel_name = c1.selectbox("상품 선택", options=item_names, key="p_box")
            
            # 선택된 아이템의 상세 정보 찾기
            item_info = next(i for i in st.session_state.item_master if i["name"] == sel_name)
            
            # 공급처 목록 추출: SUPPLIER_DETAILS 리스트 안의 SUPPLIERS['name']을 가져옴
            # ERD의 관계를 따라가야 합니다.
            supplier_options = [sd["SUPPLIERS"]["name"] for sd in item_info.get("SUPPLIER_DETAILS", [])]
            
            sel_sup = c2.selectbox(
                "공급처 선택", 
                options=supplier_options, 
                disabled=len(supplier_options) <= 1, 
                key="s_box"
            )
            
            with c3:
                st.write("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("리스트 추가", use_container_width=True):
                    key = (sel_name, sel_sup)
                    # 선택된 공급처의 상세 정보 가져오기
                    detail = next(sd for sd in item_info["SUPPLIER_DETAILS"] if sd["SUPPLIERS"]["name"] == sel_sup)
                    MOQ = detail.get("MOQ", 1) # 기본값 1
                    
                    st.session_state.manual_cart[key] = st.session_state.manual_cart.get(key, 0) + MOQ

        # 발주 목록 표시
            st.write("---")
            st.subheader(f"{st.session_state.order_mode} 발주 목록")
            
            display_items = {}
            if st.session_state.order_mode == "추천":
                for item in st.session_state.item_master:
                    # 데이터 존재 여부 확인 후 중첩 구조 접근
                    if item.get("STOCKS") and item.get("SUPPLIER_DETAILS"):
                        current_stock = item["STOCKS"][0]["stock"]
                        safety_stock = item["SUPPLIER_DETAILS"][0]["safety_stock"]
                        
                        if current_stock < safety_stock:
                            # 공급처명과 기본 발주 단위 가져오기
                            sup = item["SUPPLIER_DETAILS"][0]["SUPPLIERS"]["name"]
                            unit = item["SUPPLIER_DETAILS"][0].get("MOQ", 1)
                            # unit이 문자열일 경우를 대비해 숫자로 변환 (ERD상 int8이지만 안전하게 처리)
                            unit = int(unit) if str(unit).isdigit() else 1
                            
                            display_items[(item["name"], sup)] = st.session_state.manual_cart.get((item["name"], sup), unit)
                display_items.update(st.session_state.manual_cart)
            else:
                display_items = st.session_state.manual_cart

            total_price = 0 

            if not display_items:
                st.info("현재 발주 대기 목록이 비어 있습니다.")
            else:
                active_sups = sorted(list(set(k[1] for k in display_items.keys())))
                for sup in active_sups:         
                    with st.expander(f"🏢 공급처: {sup}", expanded=True):
                        sup_items = {k: v for k, v in display_items.items() if k[1] == sup}
                        for (name, s), qty in sup_items.items():
                            
                            # 삭제된 항목은 행 자체를 그리지 않음
                            if 'deleted_keys' in st.session_state and (name, sup) in st.session_state.deleted_keys:
                                continue

                            item_data = next(i for i in st.session_state.item_master if i["name"] == name)
                            detail = next(sd for sd in item_data["SUPPLIER_DETAILS"] if sd["SUPPLIERS"]["name"] == sup)
                            stock_val = next((stk["stock"] for stk in item_data["STOCKS"] if stk["supplier_id"] == detail["supplier_id"]), 0)
                            MOQ = int(detail.get("MOQ", 1)) if str(detail.get("MOQ")).isdigit() else 1

                            cols = st.columns([0.5, 2.5, 1.2, 3.5, 2, 1.5])                             
                            if cols[0].button("⊖", key=f"del_{name}_{sup}"):
                                # 수동 품목 삭제 기능
                                if (name, sup) in st.session_state.manual_cart:
                                    del st.session_state.manual_cart[(name, sup)]
                                
                                # 추천 품목은 숨김 리스트에 등록 (행 제거용)
                                if 'deleted_keys' not in st.session_state:
                                    st.session_state.deleted_keys = set()
                                st.session_state.deleted_keys.add((name, sup))
                                

                            # 삭제 리스트에 포함되지 않은 품목에 한하여 발주 행(Row) 정보 출력                            
                            cols[1].write(f"**{name}**")
                            cols[2].caption(f"재고:{stock_val}")                            
                            with cols[3]:
                                new_qty = st.number_input(
                                    label="수량", min_value=0, value=int(qty), step=int(MOQ),
                                    key=f"input_{name}_{sup}", label_visibility="collapsed"
                                )
                                if new_qty != qty:
                                    st.session_state.manual_cart[(name, s)] = new_qty

                            raw_price = detail.get("order_unit_price")
                            unit_price = int(raw_price) if raw_price is not None else 0
                            price = qty * unit_price
                            total_price += price

                            if unit_price > 0:
                                cols[4].write(f"**{price:,}원**")
                            else:
                                cols[4].error("단가없음")

                            cols[5].link_button("🔗발주", detail.get("order_url", "#"), use_container_width=True)

            # 최종 발주 승인
            st.divider()
            fb1, fb2 = st.columns([2, 1])
            fb1.metric("최종 발주 합계 금액", f"{total_price:,} 원")

            if fb2.button("전체 발주 완료 처리", type="primary", use_container_width=True):
                with st.spinner("DB에 발주 내역을 기록 중입니다..."):
                    try:
                        # 공급처별로 데이터 그룹화
                        orders_by_supplier = {}
                        for (name, sup_name), qty in display_items.items():
                            if sup_name not in orders_by_supplier:
                                orders_by_supplier[sup_name] = []
                            orders_by_supplier[sup_name].append({"name": name, "qty": qty})

                        # 공급처별 데이터 기록 시작
                        for sup_name, items in orders_by_supplier.items():
                            # 해당 공급처의 ID 및 단가 정보 추출
                            temp_item_data = next(i for i in st.session_state.item_master if i["name"] == items[0]["name"])
                            detail_info = next(sd for sd in temp_item_data["SUPPLIER_DETAILS"] if sd["SUPPLIERS"]["name"] == sup_name)
                            target_sup_id = detail_info["supplier_id"]
                            
                            # 공급처별 소계 금액 계산
                            subtotal = 0
                            for itm in items:
                                i_data = next(i for i in st.session_state.item_master if i["name"] == itm["name"])
                                d_info = next(sd for sd in i_data["SUPPLIER_DETAILS"] if sd["SUPPLIERS"]["name"] == sup_name)
                                price = d_info.get("order_unit_price", 0)
                                subtotal += itm["qty"] * (int(price) if price is not None else 0)
                            
                            # PURCHASE_ORDERS 테이블에 기록
                            order_data = {
                                "supplier_id": target_sup_id,
                                "total_price": int(subtotal),
                                "status": "배송중" 
                            }
                            
                            # 데이터를 insert하고 결과를 res_order에 담음
                            res_order = supabase.table("PURCHASE_ORDERS").insert(order_data).execute()
                            
                            # DB가 자동으로 생성한 order_id 가져오기
                            generated_order_id = res_order.data[0]["order_id"]

                            # PURCHASE_ITEMS 테이블 상세 기록(방금 따온 id 사용)
                            insert_items = []
                            for itm in items:
                                item_ref = next(i for i in st.session_state.item_master if i["name"] == itm["name"])
                                insert_items.append({
                                    "order_id": generated_order_id,
                                    "item_id": item_ref["id"],
                                    "actual_qty": itm["qty"]
                                })
                            
                            # 상세 내역 insert 실행
                            supabase.table("PURCHASE_ITEMS").insert(insert_items).execute()

                        # 처리 완료 후 후속 작업
                        st.cache_data.clear() #입고됐으니 재고 정보 캐시 초기화
                        st.session_state.show_toast = True
                        st.session_state.manual_cart = {}

                    except Exception as e:
                        st.error(f"발주 기록 저장 중 오류가 발생했습니다: {e}")

    if __name__ == "__main__":
        order_page()
# -------------------------------------------------------------------------------------------
# 메뉴 3: 재고 실사 (재고체크.py 기반)
# -------------------------------------------------------------------------------------------
with tab_check:
    KST = timezone(timedelta(hours=9))
    @st.cache_data
    def get_stock_data_with_prediction():
# 판매 중인 품목의 상세 정보만 먼저 가져오기
        res_details = supabase.table("SUPPLIER_DETAILS").select("item_id, supplier_id, base_unit, status").eq("status", True).execute()
        df_details = pd.DataFrame(res_details.data)
        
        # 만약 판매 중인 품목이 하나도 없다면 빈 데이터프레임 반환
        if df_details.empty:
            return pd.DataFrame()

        # 전체 재고 데이터 로드
        res_stock = supabase.table("STOCKS").select("*, ITEMS(name, category)").execute()
        df_stock = pd.DataFrame(res_stock.data)
        
        if 'ITEMS' in df_stock.columns:
            df_stock['item_name'] = df_stock['ITEMS'].apply(lambda x: x.get('name') if isinstance(x, dict) else "이름 없음")
            df_stock['category'] = df_stock['ITEMS'].apply(lambda x: x.get('category') if isinstance(x, dict) else "기타")
            df_stock = df_stock.drop(columns=['ITEMS'])

        merged_df = pd.merge(df_stock, df_details, on=['item_id', 'supplier_id'], how='inner')
        merged_df = merged_df.loc[:, ~merged_df.columns.duplicated()]
        
        now_kst = datetime.now(KST)
        predicted_stocks = []
        reliability_icons = []

        for _, row in merged_df.iterrows():
            last_check = pd.to_datetime(row['last_checked_at']).tz_convert('Asia/Seoul')
            
            # 신뢰도(신호등) 계산 로직
            time_diff = now_kst - last_check
            hours_diff = time_diff.total_seconds() / 3600
            
            if hours_diff <= 168:
                icon = "🟢" # 양호 (7일 이내)
            elif hours_diff <= 336:
                icon = "🟡" # 주의 (14일 이내)
            else:
                icon = "🔴" # 신뢰도 낮음 (14일 초과)
            
            reliability_icons.append(icon)

            # 예측 재고 계산
            weight_sum = get_total_weight(last_check, now_kst)
            reduction = row['avg_consumption'] * weight_sum
            predicted_val = max(0, row['stock'] - reduction)
            predicted_stocks.append(round(predicted_val, 2))
        
        merged_df['신뢰도'] = reliability_icons
        merged_df['predicted_stock'] = predicted_stocks
        return merged_df

    st.title("재고 실사")

    df = get_stock_data_with_prediction()
    df['새로운 재고량'] = None
    st.subheader("오늘의 재고 점검 리스트")
    
    # 도움말 업데이트
    st.info("""
    💡 **예측 신호등 안내**
    - 🟢: 실사 후 7일 이내 | 🟡: 실사 14일 이내 | 🔴: 실사 14일 초과
    """)

    updated_dfs = []
    categories = sorted(df['category'].unique())

    for cat in categories:
        with st.expander(f"📂 {cat}", expanded=True):
            cat_df = df[df['category'] == cat].copy()
            
            # data_editor 설정에 '신뢰도' 추가
            edited_cat_df = st.data_editor(
                cat_df[['신뢰도', 'item_name', 'predicted_stock', 'base_unit', '새로운 재고량', 'item_id', 'supplier_id', 'last_checked_at', 'avg_consumption', 'stock']],
                column_config={
                    "신뢰도": st.column_config.TextColumn("상태", help="마지막 실사 후 경과 시간 기준 신뢰도"),
                    "item_id": None, "supplier_id": None, "avg_consumption": None, "stock": None,
                    "item_name": "품목명",
                    "predicted_stock": st.column_config.NumberColumn("예측 재고(장부)", format="%.2f"),
                    "base_unit": "단위",
                    "새로운 재고량": st.column_config.NumberColumn("실사 입력", min_value=0, step=1),
                    "last_checked_at": st.column_config.DatetimeColumn("마지막 실사일", format="YYYY-MM-DD HH:mm")
                },
                disabled=["신뢰도", "item_name", "predicted_stock", "base_unit", "last_checked_at"],
                hide_index=True,
                use_container_width=True,
                key=f"editor_{cat}"
            )
            updated_dfs.append(edited_cat_df)
    
    if updated_dfs:
        final_edited_df = pd.concat(updated_dfs)

    # 재고 반영 및 학습 버튼
    if st.button("실사 반영", type="primary"):
        updates = final_edited_df[final_edited_df['새로운 재고량'].notnull()]
        
        if not updates.empty:
            with st.spinner("데이터 반영 중..."):
                try:
                    kst = timezone(timedelta(hours=9))
                    now_kst = datetime.now(kst)
                    success_count = 0
                    
                    for index, row in updates.iterrows():
                        try:
                            def extract_scalar(v):
                                if isinstance(v, (pd.Series, list, pd.Index)):
                                    return v.iloc[0] if hasattr(v, 'iloc') else v[0]
                                return v

                            # 모든 변수 추출 시 extract_scalar를 적용하여 float() 에러 방지
                            actual_qty = float(extract_scalar(row['새로운 재고량']))
                            current_stock = float(extract_scalar(row['stock']))
                            predicted_stock = float(extract_scalar(row['predicted_stock']))
                            avg_cons = float(extract_scalar(row['avg_consumption']))
                            item_id = int(extract_scalar(row['item_id']))
                            supplier_id = int(extract_scalar(row['supplier_id']))
                            
                            # 시간 데이터 처리
                            last_val = extract_scalar(row['last_checked_at'])
                            last_check_dt = pd.to_datetime(last_val)
                            # 시간대(Timezone) 정보가 없으면 한국 시간(KST)으로 적용
                            if last_check_dt.tzinfo is None:
                                last_check_dt = last_check_dt.replace(tzinfo=timezone.utc).astimezone(KST)
                            else:
                                # 이미 시간대 정보가 있다면 그대로 한국 시간으로 변환
                                last_check_dt = last_check_dt.astimezone(KST)

                            # 예측 재고 계산
                            weight_sum = get_total_weight(last_check_dt, now_kst)
                            usage_diff = current_stock - actual_qty
                            actual_daily_usage = usage_diff / max(weight_sum, 0.1)
                            alpha = 0.3 #최근 변화율을 0.3만큼 가중치를 주고 학습
                            new_avg = (avg_cons * (1 - alpha)) + (max(0, actual_daily_usage) * alpha)
                            error_rate = (abs(float(actual_qty - predicted_stock)) / predicted_stock * 100) if predicted_stock > 0 else 0
                            
                            # DB 업데이트 실행
                            supabase.table("STOCKS").update({
                                "stock": actual_qty,
                                "avg_consumption": float(new_avg),
                                "last_checked_at": now_kst.strftime('%Y-%m-%dT%H:%M:%S+09:00')                            }).match({
                                "item_id": item_id,
                                "supplier_id": supplier_id
                            }).execute()
                            
                            # STOCK_LOGS 테이블 기록 
                            supabase.table("STOCK_LOGS").insert({
                                "item_id": item_id,
                                "supplier_id": supplier_id,
                                "exp_stock": predicted_stock,               # 예측 재고
                                "act_stock": int(actual_qty),               # 실사 재고
                                "error": float(actual_qty - predicted_stock), # 오차 (실사 - 예측)
                                "error_rate": round(error_rate, 2),
                                "last_checked_at": now_kst.strftime('%Y-%m-%dT%H:%M:%S+09:00'),
                                "old_avg_consumption": avg_cons,            # 이전 평균 소모량
                                "new_avg_consumption": float(new_avg)       # 새로운 평균 소모량
                            }).execute()

                            success_count += 1

                        except Exception as row_err:
                            # 어떤 품목에서, 어떤 값 때문에 에러가 났는지 상세히 출력
                            st.error(f"⚠️ '{row['item_name']}' 처리 중 에러: {row_err}")
                            continue
                    
                    if success_count > 0:
                        st.toast(f"✅ {success_count}개 품목의 실사 결과가 반영되었습니다.")
                        st.cache_data.clear() # 입고됐으니 재고 정보 캐시 초기화

                except Exception as e:
                    st.error(f"오류 발생: {e}")
# -------------------------------------------------------------------------------------------
# 메뉴 4: 마스터 관리창 (품목등록.py 기반)
# -------------------------------------------------------------------------------------------
with tab_admin:
    adm_t1, adm_t2 = st.tabs(["신규 품목/공급처 등록", "DB 테이블 직접 수정"])
    
    with adm_t1:
        st.subheader("품목 등록")
        # 기존 공급처 목록 로드
        res_sup = supabase.table("SUPPLIERS").select("id, name").execute()
        sup_dict = {s['name']: s['id'] for s in res_sup.data}
        sup_list = ["+ 신규 공급처 직접 입력"] + list(sup_dict.keys())
        
        with st.form("new_registration_form", clear_on_submit=False):
            c1, c2 = st.columns(2)
            
            with c1:
                st.markdown("### **기본 정보**")
                sel_sup = st.selectbox("공급처 선택", options=sup_list)
                new_sup_name = st.text_input("신규 공급처 이름 (신규 선택 시 필수)")
                item_name = st.text_input("품목 이름 (예: 원두 1kg)")
                category = st.text_input("카테고리 (예: 시럽)")

            with c2:
                st.markdown("### **발주 설정**")
                order_url = st.text_input("주문 URL (선택 사항)")
                order_unit = st.text_input("주문 단위 (예: 박스, 팩)")
                moq = st.number_input("MOQ (최소 주문 수량)", min_value=1, value=1)
                unit_price = st.number_input("주문 단위당 가격 (원)", min_value=0, step=100)

            st.divider()
                
            st.markdown("### **재고 및 단위 환산 설정**")
            cc1, cc2, cc3 = st.columns(3)
            base_unit = cc1.text_input("재고 관리 단위 (예: 개, g, ml)")
            conv_factor = cc2.number_input("환산 계수 (1주문단위당 낱개 수)", min_value=1, value=1)
            safety_stock = cc3.number_input("안전재고 (낱개 기준)", min_value=0)

            if st.form_submit_button("전체 데이터 등록 실행", type="primary"):
                # 필수 값 검증 로직: URL을 제외한 모든 필드가 채워졌는지 확인
                is_sup_valid = (sel_sup != "+ 신규 공급처 직접 입력") or (sel_sup == "+ 신규 공급처 직접 입력" and new_sup_name)
                required_fields = [item_name, category, order_unit, base_unit]
                
                if not all(required_fields) or not is_sup_valid:
                    st.error("🚨 오류: 주문 URL을 제외한 모든 항목을 정확히 입력해주세요.")
                else:
                    try:
                        # 1. 공급처(SUPPLIERS) ID 확보
                        if sel_sup == "+ 신규 공급처 직접 입력":
                            ex_sup = supabase.table("SUPPLIERS").select("id").eq("name", new_sup_name).execute()
                            if ex_sup.data:
                                target_sup_id = ex_sup.data[0]['id']
                            else:
                                sup_res = supabase.table("SUPPLIERS").insert({"name": new_sup_name}).execute()
                                target_sup_id = sup_res.data[0]['id']
                        else:
                            target_sup_id = sup_dict[sel_sup]

                        # 2. 품목(ITEMS) ID 확보
                        ex_itm = supabase.table("ITEMS").select("id").eq("name", item_name).execute()
                        if ex_itm.data:
                            target_item_id = ex_itm.data[0]['id']
                        else:
                            itm_res = supabase.table("ITEMS").insert({"name": item_name, "category": category}).execute()
                            target_item_id = itm_res.data[0]['id']

                        # 3. 상세정보(SUPPLIER_DETAILS) 등록
                        supabase.table("SUPPLIER_DETAILS").upsert({
                            "item_id": target_item_id,
                            "supplier_id": target_sup_id,
                            "order_url": order_url,
                            "order_unit": order_unit,
                            "MOQ": moq,
                            "order_unit_price": unit_price,
                            "safety_stock": safety_stock,
                            "base_unit": base_unit,
                            "conversion_factor": conv_factor
                        }).execute()

                        # 4. 재고(STOCKS) 초기화
                        ex_stk = supabase.table("STOCKS").select("*").match({"item_id": target_item_id, "supplier_id": target_sup_id}).execute()
                        if not ex_stk.data:
                            supabase.table("STOCKS").insert({
                                "item_id": target_item_id,
                                "supplier_id": target_sup_id,
                                "stock": 0,
                                "avg_consumption": 0,
                                "last_checked_at": datetime.now(timezone.utc).isoformat()
                            }).execute()
                        st.cache_data.clear()
                        st.success(f"✅ '{item_name}' 등록이 완료되었습니다!")
                        st.balloons()
                    except Exception as e:
                        st.error(f"❌ 등록 중 오류 발생: {e}")
        
        st.divider()

        #품목 판매 상태 관리
        st.subheader("판매 상태 관리 (ON/OFF)")
        st.info("더 이상 판매(발주)하지 않는 품목은 여기서 OFF로 설정하세요. 발주 추천 목록에서 제외됩니다.")
        res_active = supabase.table("SUPPLIER_DETAILS").select("item_id, supplier_id, status, ITEMS(name), SUPPLIERS(name)").execute()
        
        if res_active.data:
            df_active = pd.DataFrame(res_active.data)
            # 가독성을 위해 이름 추출
            df_active['display_name'] = df_active.apply(
                lambda x: f"[{x['SUPPLIERS']['name']}] {x['ITEMS']['name']}", axis=1
            )
            
            # 품목 선택 드롭다운
            target_display = st.selectbox("상태를 변경할 품목 선택", options=df_active['display_name'].tolist())
            
            # 선택된 품목의 현재 상태 찾기
            selected_row = df_active[df_active['display_name'] == target_display].iloc[0]
            current_status = bool(selected_row['status'])
            
            c1, c2 = st.columns([2, 1])
            with c1:
                # True/False 선택
                new_status = st.radio(
                    f"**{target_display}**의 현재 상태: {'🟢 판매 중' if current_status else '🔴 판매 중단'}",
                    options=[True, False],
                    format_func=lambda x: "판매 중 (ON)" if x else "판매 중단 (OFF/단종)",
                    index=0 if current_status else 1,
                    horizontal=True
                )
            
            with c2:
                st.write("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("상태 저장", use_container_width=True):
                    try:
                        supabase.table("SUPPLIER_DETAILS").update({"status": new_status}).match({
                            "item_id": selected_row['item_id'],
                            "supplier_id": selected_row['supplier_id']
                        }).execute()
                        st.success(f"✅ 변경 완료: {target_display} -> {'ON' if new_status else 'OFF'}")
                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"상태 변경 중 오류 발생: {e}")
        else:
            st.write("등록된 품목이 없습니다.")
    with adm_t2:
        target_tab = st.selectbox("수정할 테이블 선택", ["ITEMS", "STOCKS", "SUPPLIERS", "SUPPLIER_DETAILS", "PURCHASE_ORDERS", "PURCHASE_ITEMS"])
        
        res = supabase.table(target_tab).select("*").execute()
        df = pd.DataFrame(res.data)
        
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True, key=f"admin_editor_{target_tab}")
        
        if st.button(f"{target_tab} 데이터 반영", type="primary"):
            try:
                updated_data = edited_df.to_dict(orient='records')
                supabase.table(target_tab).upsert(updated_data).execute()
                st.success(f"✅ {target_tab} 업데이트 성공!")
                st.cache_data.clear()
            except Exception as e:
                st.error(f"❌ 반영 실패: {e}")

# -------------------------------------------------------------------------------------------
# 메뉴 5: AI 참모 (추가 기능)
# -------------------------------------------------------------------------------------------
with tab_chat:
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