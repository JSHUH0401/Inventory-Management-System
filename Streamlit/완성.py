import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

# --- [1. 기본 설정 및 DB 연결] ---
url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_KEY"]
KST = timezone(timedelta(hours=9)) # 한국 표준시 설정

@st.cache_resource
def init_connection():
    return create_client(url, key)

supabase = init_connection()

# --- [2. 공통 유틸리티 함수] ---
def get_total_weight(start_date, end_date):
    """두 날짜 사이의 요일별 소모 가중치 합계 계산"""
    weekday_factors = {0: 0.8, 4: 1.2, 5: 1.5, 6: 1.3}
    total_weight = 0
    current = start_date.astimezone(timezone.utc) + timedelta(days = 1)
    now = end_date.astimezone(timezone.utc)
    while current <= now:
        factor = weekday_factors.get(current.weekday(), 1.0)
        total_weight += factor
        current += timedelta(days=1)
    return total_weight

# --- [3. 통합 데이터 로드 (PGRST200 에러 방지용 Pandas Merge 방식)] ---
def get_unified_data():
    """STOCKS, ITEMS, SUPPLIER_DETAILS를 수동으로 병합"""
    # STOCKS + ITEMS (이름, 카테고리)
    res_s = supabase.table("STOCKS").select("*, ITEMS(name, category)").execute()
    df_s = pd.DataFrame(res_s.data)
    if not df_s.empty:
        df_s['item_name'] = df_s['ITEMS'].apply(lambda x: x.get('name') if isinstance(x, dict) else "N/A")
        df_s['category'] = df_s['ITEMS'].apply(lambda x: x.get('category') if isinstance(x, dict) else "기타")
    
    # SUPPLIER_DETAILS (안전재고, 단위, 환산계수)
    res_d = supabase.table("SUPPLIER_DETAILS").select("*").execute()
    df_d = pd.DataFrame(res_d.data) if 'res_details' in locals() else pd.DataFrame(res_d.data)

    if df_s.empty: return pd.DataFrame()
    # Pandas에서 ID 기반으로 안전하게 병합
    merged = pd.merge(df_s, df_d, on=['item_id', 'supplier_id'], how='left')
    return merged.loc[:, ~merged.columns.duplicated()]

# --- [4. 상단 메뉴 구성 (Tabs)] ---
st.set_page_config(page_title="만월경 통합 관리", layout="wide")
tab_dash, tab_order, tab_check, tab_admin = st.tabs(["실시간 대시보드", "발주 관리", "재고 실사", "마스터 관리창"])

# -------------------------------------------------------------------------------------------
# 메뉴 1: 실시간 대시보드 & 입고 (대시보드.py 기반)
# -------------------------------------------------------------------------------------------
with tab_dash:
    st.title("실시간 재고 모니터링")
    df = get_unified_data()
    now_kst = datetime.now(KST)
    
    # 예측 재고 계산
    predicted_list = []
    for _, row in df.iterrows():
        lc = pd.to_datetime(row['last_checked_at']).tz_convert('Asia/Seoul')
        pred = max(0, row['stock'] - (row['avg_consumption'] * get_total_weight(lc, now_kst)))
        predicted_list.append({**row, "예측재고": round(pred, 2)})
    
    res_df = pd.DataFrame(predicted_list)
    danger = res_df[res_df['예측재고'] < res_df['safety_stock']]
    
    c1, c2 = st.columns(2)
    c1.metric("전체 품목", len(res_df))
    c2.metric("발주 필요", len(danger), delta_color="inverse")
    
    if not danger.empty:
        st.subheader("⚠️ 안전재고 미달 품목")
        st.dataframe(danger[['category', 'item_name', '예측재고', 'safety_stock', 'base_unit']], use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("배송 중인 주문 및 입고 처리")
    # 배송 현황 로드
    res_o = supabase.table("PURCHASE_ORDERS").select("*, SUPPLIERS(name)").eq("status", "배송중").execute()
    orders = pd.DataFrame(res_o.data)
    
    if orders.empty: st.info("배송 중인 내역이 없습니다.")
    else:
        for _, order in orders.iterrows():
            oid = order['order_id']
            col_info, col_btn = st.columns([5, 1])
            with col_info:
                #texp = st.expander(f"📦 주문 {order['SUPPLIERS']['name']} (결제액: {order['total_price']:,}원)")
                for _, order in orders.iterrows():
                    oid = order['order_id']
                    col_info, col_btn = st.columns([5, 1])
                    with col_info:
                        # 1. expander 선언
                        exp = st.expander(f"📦 주문 {order['SUPPLIERS']['name']} (결제액: {order['total_price']:,}원)")
                        
                        # 2. [추가] expander 내부에 상세 품목 표시
                        with exp:
                            # 해당 주문에 속한 아이템들 가져오기
                            items_res = supabase.table("PURCHASE_ITEMS").select("*, ITEMS(name)").eq("order_id", oid).execute()
                            if items_res.data:
                                for itm in items_res.data:
                                    # 품목명과 수량 표시
                                    item_name = itm['ITEMS']['name']
                                    qty = itm['actual_qty']
                                    st.write(f"- {item_name}: **{qty}** 개")
                            else:
                                st.write("상세 품목 정보가 없습니다.")
            with col_btn:
                st.write("<div style='height: 5px;'></div>", unsafe_allow_html=True)
                if st.button("입고완료", key=f"rec_{oid}", use_container_width=True):
                    # 입고 처리: 단위 환산(conversion_factor) 적용
                    items_res = supabase.table("PURCHASE_ITEMS").select("*").eq("order_id", oid).execute()
                    for itm in items_res.data:
                        # 환산 계수 조인 없이 가져오기 위해 세부 데이터 다시 활용
                        details = supabase.table("SUPPLIER_DETAILS").select("conversion_factor").match({"item_id": itm['item_id'], "supplier_id": order['supplier_id']}).execute()
                        cf = details.data[0]['conversion_factor'] if details.data else 1
                        inc_qty = itm['actual_qty'] * cf
                        
                        curr_stock = supabase.table("STOCKS").select("stock").match({"item_id": itm['item_id'], "supplier_id": order['supplier_id']}).execute().data[0]['stock']
                        supabase.table("STOCKS").update({"stock": float(curr_stock + inc_qty)}).match({"item_id": itm['item_id'], "supplier_id": order['supplier_id']}).execute()
                    
                    supabase.table("PURCHASE_ORDERS").update({"status": "입고완료"}).eq("order_id", oid).execute()
                    st.rerun()

# -------------------------------------------------------------------------------------------
# 메뉴 2: 발주 관리 (발주창v2.py 기반)
# -------------------------------------------------------------------------------------------
with tab_order:
        # 1. 앱 최상단(상태 관리 변수 정의 구역)에 추가
    if 'show_toast' not in st.session_state:
        st.session_state.show_toast = False

    # 2. 토스트 메시지 출력 로직 (레이아웃 상단이나 적절한 위치에 배치)
    if st.session_state.show_toast:
        st.toast("발주 완료 처리되었습니다.")
        st.session_state.show_toast = False # 메시지를 한 번 보여준 후 다시 꺼줌

    #########################################################################

    # 1. 초기 데이터 설정
    def load_data():
        # ERD 구조에 맞춰 Join 쿼리를 날립니다.
        # ITEMS를 가져오면서 연결된 상세정보와 재고를 한꺼번에 가져옴
        query = """
            id, name,
            SUPPLIER_DETAILS (
                supplier_id, order_url, MOQ, safety_stock, order_unit_price,
                SUPPLIERS ( name )
            ),
            STOCKS ( stock, supplier_id )
        """
        response = supabase.table("ITEMS").select(query).execute()
        return response.data

    if 'item_master' not in st.session_state:
        st.session_state.item_master = load_data()

    ###############################################################################################

    # 상태 관리 변수 [cite: 19]
    if 'order_mode' not in st.session_state:
        st.session_state.order_mode = "추천"
    if 'manual_cart' not in st.session_state:
        st.session_state.manual_cart = {}

    # CSS: 버튼 색상 변경 및 정렬 미세조정
    st.markdown("""
        <style>
        /* 1. 최상단 메인 제목 (st.title) 스타일 */
        .stApp h1 {
            font-size: 28px !important;
            font-weight: 700 !important;
\            padding-top: 0px !important;
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

    def order_page():
        st.title("만월경 발주 관리")
        
        # --- 1. 발주 모드 선택 영역  ---
        st.write("### 📂 발주 모드 선택")
        col_rec, col_cus = st.columns(2)
        
        with col_rec:
            rec_style = "primary" if st.session_state.order_mode == "추천" else "secondary"
            if st.button("시스템 추천 발주", use_container_width=True, type=rec_style):
                st.session_state.order_mode = "추천"
                st.session_state.manual_cart = {}
                st.rerun()

        with col_cus:
            cus_style = "primary" if st.session_state.order_mode == "커스텀" else "secondary"
            if st.button("커스텀 발주", use_container_width=True, type=cus_style):
                st.session_state.order_mode = "커스텀"
                st.session_state.manual_cart = {}
                st.rerun()

        # --- 2. 품목 직접 추가 섹션 수정 ---
        with st.container(border=True):
            st.subheader("품목 직접 추가")
            c1, c2, c3 = st.columns([4, 4, 1.5])
            
            # [수정] item_names 가져오기 (item_name -> name)
            item_names = [i["name"] for i in st.session_state.item_master]
            sel_name = c1.selectbox("상품 선택", options=item_names, key="p_box")
            
            # [수정] 선택된 아이템의 상세 정보 찾기
            item_info = next(i for i in st.session_state.item_master if i["name"] == sel_name)
            
            # [수정] 공급처 목록 추출: SUPPLIER_DETAILS 리스트 안의 SUPPLIERS['name']을 가져옴
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
                    # 발주 단위(unit)도 이제 SUPPLIER_DETAILS에서 가져와야 합니다.
                    # 선택된 공급처의 상세 정보를 찾음
                    detail = next(sd for sd in item_info["SUPPLIER_DETAILS"] if sd["SUPPLIERS"]["name"] == sel_sup)
                    MOQ = detail.get("MOQ", 1) # 기본값 1
                    
                    st.session_state.manual_cart[key] = st.session_state.manual_cart.get(key, 0) + MOQ
                    st.rerun()

        # --- 3. 발주 목록 표시 (ERD 구조에 맞게 수정) ---
            st.write("---")
            st.subheader(f"{st.session_state.order_mode} 발주 목록")
            
            display_items = {}
            if st.session_state.order_mode == "추천":
                for item in st.session_state.item_master:
                    # [수정] 데이터 존재 여부 확인 후 중첩 구조 접근
                    if item.get("STOCKS") and item.get("SUPPLIER_DETAILS"):
                        current_stock = item["STOCKS"][0]["stock"]
                        safety_stock = item["SUPPLIER_DETAILS"][0]["safety_stock"]
                        
                        if current_stock < safety_stock:
                            # [수정] 공급처명과 기본 발주 단위 가져오기
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
                # [삭제] 기존의 total_price = 0 줄은 지워주세요.

                for sup in active_sups:         
                    with st.expander(f"🏢 공급처: {sup}", expanded=True):
                        sup_items = {k: v for k, v in display_items.items() if k[1] == sup}
                        for (name, s), qty in sup_items.items():
                            
                            # --- [추가] 삭제된 항목은 행 자체를 그리지 않음 ---
                            if 'deleted_keys' in st.session_state and (name, sup) in st.session_state.deleted_keys:
                                continue
                            # -----------------------------------------------

                            item_data = next(i for i in st.session_state.item_master if i["name"] == name)
                            detail = next(sd for sd in item_data["SUPPLIER_DETAILS"] if sd["SUPPLIERS"]["name"] == sup)
                            stock_val = next((stk["stock"] for stk in item_data["STOCKS"] if stk["supplier_id"] == detail["supplier_id"]), 0)
                            MOQ = int(detail.get("MOQ", 1)) if str(detail.get("MOQ")).isdigit() else 1

                            cols = st.columns([0.5, 2.5, 1.2, 3.5, 2, 1.5]) 
                            
                            if cols[0].button("⊖", key=f"del_{name}_{sup}"):
                                # 1. 수동 추가 품목 삭제
                                if (name, sup) in st.session_state.manual_cart:
                                    del st.session_state.manual_cart[(name, sup)]
                                
                                # 2. 추천 품목은 숨김 리스트에 등록 (행 제거용)
                                if 'deleted_keys' not in st.session_state:
                                    st.session_state.deleted_keys = set()
                                st.session_state.deleted_keys.add((name, sup))
                                
                                st.rerun()

                            # 이 아래 코드들이 실행되지 않아야 행이 남지 않습니다.
                            cols[1].write(f"**{name}**")
                            cols[2].caption(f"재고:{stock_val}")                            
                            with cols[3]:
                                new_qty = st.number_input(
                                    label="수량", min_value=0, value=int(qty), step=int(MOQ),
                                    key=f"input_{name}_{sup}", label_visibility="collapsed"
                                )
                                if new_qty != qty:
                                    st.session_state.manual_cart[(name, s)] = new_qty
                                    st.rerun()

                            raw_price = detail.get("order_unit_price")
                            unit_price = int(raw_price) if raw_price is not None else 0
                            price = qty * unit_price
                            total_price += price

                            if unit_price > 0:
                                cols[4].write(f"**{price:,}원**")
                            else:
                                cols[4].error("단가없음")

                            cols[5].link_button("🔗발주", detail.get("order_url", "#"), use_container_width=True)

            # --- 4. 최종 발주 승인 ---
            st.divider()
            fb1, fb2 = st.columns([2, 1])
            fb1.metric("최종 발주 합계 금액", f"{total_price:,} 원")

            if fb2.button("전체 발주 완료 처리", type="primary", use_container_width=True):
                with st.spinner("DB에 발주 내역을 기록 중입니다..."):
                    try:
                        # 1. 공통 order_id 생성: DB에서 현재 가장 큰 order_id를 찾아 +1 합니다.
                        #max_order_res = supabase.table("PURCHASE_ORDERS").select("order_id").order("order_id", desc=True).limit(1).execute()
                        #shared_order_id = (max_order_res.data[0]["order_id"] + 1) if max_order_res.data else 1

                        # 2. 공급처별로 데이터 그룹화
                        orders_by_supplier = {}
                        for (name, sup_name), qty in display_items.items():
                            if sup_name not in orders_by_supplier:
                                orders_by_supplier[sup_name] = []
                            orders_by_supplier[sup_name].append({"name": name, "qty": qty})

                        # 3. 공급처별 데이터 기록 시작
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

                            # --- [핵심 수정 구간] ---
                            
                            # A. PURCHASE_ORDERS 테이블 기록
                            order_data = {
                                "supplier_id": target_sup_id,
                                "total_price": int(subtotal),
                                "status": "배송중" 
                                # ordered_at은 DB에서 자동으로 기록되도록 설정되어 있다고 가정합니다.
                            }
                            
                            # 데이터를 insert하고 결과를 변수에 담습니다.
                            res_order = supabase.table("PURCHASE_ORDERS").insert(order_data).execute()
                            
                            # DB가 자동으로 생성한 order_id를 가져옵니다. (리스트의 첫 번째 항목)
                            generated_order_id = res_order.data[0]["order_id"]

                            # B. PURCHASE_ITEMS 테이블 상세 기록 (방금 따온 id 사용)
                            insert_items = []
                            for itm in items:
                                item_ref = next(i for i in st.session_state.item_master if i["name"] == itm["name"])
                                insert_items.append({
                                    "order_id": generated_order_id, # <--- 여기가 핵심!
                                    "item_id": item_ref["id"],
                                    "actual_qty": itm["qty"]
                                })
                            
                            # 상세 내역 insert 실행
                            supabase.table("PURCHASE_ITEMS").insert(insert_items).execute()

                        # 4. 처리 완료 후 후속 작업 (재고 업데이트는 생략)
                        st.session_state.show_toast = True
                        st.session_state.manual_cart = {}
                        st.rerun()

                    except Exception as e:
                        st.error(f"발주 기록 저장 중 오류가 발생했습니다: {e}")

    if __name__ == "__main__":
        order_page()
# -------------------------------------------------------------------------------------------
# 메뉴 3: 재고 실사 (재고체크.py 기반)
# -------------------------------------------------------------------------------------------
# --- [메뉴 3: 재고 실사 부분 수정] ---
with tab_check:
    KST = timezone(timedelta(hours=9))

    def get_stock_data_with_prediction():
        # 1. DB 데이터 로드 (STOCKS + ITEMS)
        res_stock = supabase.table("STOCKS").select("*, ITEMS(name, category)").execute()
        df_stock = pd.DataFrame(res_stock.data)
        
        if 'ITEMS' in df_stock.columns:
            df_stock['item_name'] = df_stock['ITEMS'].apply(lambda x: x.get('name') if isinstance(x, dict) else "이름 없음")
            df_stock['category'] = df_stock['ITEMS'].apply(lambda x: x.get('category') if isinstance(x, dict) else "기타")
            df_stock = df_stock.drop(columns=['ITEMS'])

        res_details = supabase.table("SUPPLIER_DETAILS").select("item_id, supplier_id, base_unit").execute()
        df_details = pd.DataFrame(res_details.data)

        merged_df = pd.merge(df_stock, df_details, on=['item_id', 'supplier_id'], how='left')
        merged_df = merged_df.loc[:, ~merged_df.columns.duplicated()]
        
        now_kst = datetime.now(KST)
        predicted_stocks = []
        reliability_icons = [] # 신호등 리스트 추가

        for _, row in merged_df.iterrows():
            last_check = pd.to_datetime(row['last_checked_at']).tz_convert('Asia/Seoul')
            
            # [추가] 신뢰도(신호등) 계산 로직
            time_diff = now_kst - last_check
            hours_diff = time_diff.total_seconds() / 3600
            
            if hours_diff <= 24:
                icon = "🟢" # 신선함 (24시간 이내)
            elif hours_diff <= 72:
                icon = "🟡" # 주의 (3일 이내)
            else:
                icon = "🔴" # 신뢰도 낮음 (3일 초과)
            
            reliability_icons.append(icon)

            # 예측 재고 계산
            weight_sum = get_total_weight(last_check, now_kst)
            reduction = row['avg_consumption'] * weight_sum
            predicted_val = max(0, row['stock'] - reduction)
            predicted_stocks.append(round(predicted_val, 2))
        
        merged_df['신뢰도'] = reliability_icons # 컬럼 추가
        merged_df['predicted_stock'] = predicted_stocks
        return merged_df

    st.title("재고 실사")

    df = get_stock_data_with_prediction()
    df['새로운 재고량'] = None

    st.subheader("오늘의 재고 점검 리스트")
    # 도움말 업데이트
    st.info("""
    💡 **예측 신호등 안내**
    - 🟢 (높음): 실사 24시간 이내 | 🟡 (보통): 실사 3일 이내 | 🔴 (낮음): 실사 3일 초과 (실사 권장)
    """)

    updated_dfs = []
    categories = sorted(df['category'].unique())

    for cat in categories:
        with st.expander(f"📂 {cat}", expanded=True):
            cat_df = df[df['category'] == cat].copy()
            
            # [수정] data_editor 설정에 '신뢰도' 추가
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

    # 4. 재고 반영 및 학습 버튼 (로직 생략 - 기존과 동일)
    if st.button("실사 반영", type="primary"):
        updates = final_edited_df[final_edited_df['새로운 재고량'].notnull()]
        
        if not updates.empty:
            with st.spinner("데이터 반영 중..."):
                try:
                    kst = timezone(timedelta(hours=9))
                    now_kst = datetime.now(kst)
                    success_count = 0
                    
                    # 4. 재고 반영 및 학습 버튼 내부 수정
                    for index, row in updates.iterrows():
                        try:
                            # [1단계] 데이터 추출 전 디버깅 (에러 발생 시 화면에 원인 출력)
                            raw_val = row['새로운 재고량']
                            
                            # [2단계] 리스트/시리즈 여부 체크 및 강제 스칼라 변환
                            if isinstance(raw_val, (pd.Series, list, pd.Index)):
                                # 중복 컬럼 등으로 인해 리스트가 들어온 경우 첫 번째 값만 선택
                                actual_qty = float(raw_val.iloc[0]) if hasattr(raw_val, 'iloc') else float(raw_val[0])
                            else:
                                actual_qty = float(raw_val)

                            # [3단계] 다른 변수들도 동일하게 안전하게 추출 (중복 컬럼 대비)
                            def get_value(r, col):
                                v = r[col]
                                if isinstance(v, (pd.Series, list)):
                                    return v.iloc[0] if hasattr(v, 'iloc') else v[0]
                                return v

                            current_stock = float(get_value(row, 'stock'))
                            avg_cons = float(get_value(row, 'avg_consumption'))
                            item_id = int(get_value(row, 'item_id'))
                            supplier_id = int(get_value(row, 'supplier_id'))

                            # --- 이후 학습 및 DB 업데이트 로직은 동일 ---
                            last_val = get_value(row, 'last_checked_at')
                            last_check_dt = pd.to_datetime(last_val)

                            # 2. 시간대(Timezone) 정보가 없으면 UTC를 입힌 후 한국 시간(KST)으로 변환
                            if last_check_dt.tzinfo is None:
                                last_check_dt = last_check_dt.replace(tzinfo=timezone.utc).astimezone(KST)
                            else:
                                # 이미 시간대 정보가 있다면 그대로 한국 시간으로 변환
                                last_check_dt = last_check_dt.astimezone(KST)

                            # 3. 이제 계산 (둘 다 KST 객체라 에러가 나지 않습니다)
                            weight_sum = get_total_weight(last_check_dt, now_kst)
                            usage_diff = current_stock - actual_qty
                            actual_daily_usage = usage_diff / max(weight_sum, 0.1)
                            
                            alpha = 0.3
                            new_avg = (avg_cons * (1 - alpha)) + (max(0, actual_daily_usage) * alpha)
                            
                            # DB 업데이트 실행
                            supabase.table("STOCKS").update({
                                "stock": actual_qty,
                                "avg_consumption": float(new_avg),
                                "last_checked_at": now_kst.strftime('%Y-%m-%dT%H:%M:%S+09:00')                            }).match({
                                "item_id": item_id,
                                "supplier_id": supplier_id
                            }).execute()
                            
                            success_count += 1

                        except Exception as row_err:
                            # 어떤 품목에서, 어떤 값 때문에 에러가 났는지 상세히 출력
                            st.error(f"⚠️ '{row['item_name']}' 처리 중 에러: {row_err}")
                            st.write("문제가 된 데이터 실제 형태:", raw_val)
                            continue
                    
                    if success_count > 0:
                        st.toast(f"✅ {success_count}개 품목의 실사 결과가 반영되었습니다.")
                        st.rerun()

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

            st.divider() # --- 구분선 ---
            
            st.markdown("### **재고 및 단위 환산 설정**")
            cc1, cc2, cc3 = st.columns(3)
            # 사장님 요청 순서: 재고관리단위 -> 환산계수 -> 안전재고
            base_unit = cc1.text_input("재고 관리 단위 (예: 개, g, ml)")
            conv_factor = cc2.number_input("환산 계수 (1주문단위당 낱개 수)", min_value=1, value=1)
            safety_stock = cc3.number_input("안전재고 (낱개 기준)", min_value=0)

            if st.form_submit_button("전체 데이터 등록 실행", type="primary"):
                # --- [필수 값 검증 로직] ---
                # URL을 제외한 모든 필드가 채워졌는지 확인
                is_sup_valid = (sel_sup != "+ 신규 공급처 직접 입력") or (sel_sup == "+ 신규 공급처 직접 입력" and new_sup_name)
                required_fields = [item_name, category, order_unit, base_unit]
                
                if not all(required_fields) or not is_sup_valid:
                    st.error("🚨 오류: 주문 URL을 제외한 모든 항목을 정확히 입력해주세요.")
                else:
                    try:
                        # STEP 1: 공급처(SUPPLIERS) ID 확보
                        if sel_sup == "+ 신규 공급처 직접 입력":
                            ex_sup = supabase.table("SUPPLIERS").select("id").eq("name", new_sup_name).execute()
                            if ex_sup.data:
                                target_sup_id = ex_sup.data[0]['id']
                            else:
                                sup_res = supabase.table("SUPPLIERS").insert({"name": new_sup_name}).execute()
                                target_sup_id = sup_res.data[0]['id']
                        else:
                            target_sup_id = sup_dict[sel_sup]

                        # STEP 2: 품목(ITEMS) ID 확보
                        ex_itm = supabase.table("ITEMS").select("id").eq("name", item_name).execute()
                        if ex_itm.data:
                            target_item_id = ex_itm.data[0]['id']
                        else:
                            itm_res = supabase.table("ITEMS").insert({"name": item_name, "category": category}).execute()
                            target_item_id = itm_res.data[0]['id']

                        # STEP 3: 상세정보(SUPPLIER_DETAILS) 등록
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

                        # STEP 4: 재고(STOCKS) 초기화
                        ex_stk = supabase.table("STOCKS").select("*").match({"item_id": target_item_id, "supplier_id": target_sup_id}).execute()
                        if not ex_stk.data:
                            supabase.table("STOCKS").insert({
                                "item_id": target_item_id,
                                "supplier_id": target_sup_id,
                                "stock": 0,
                                "avg_consumption": 0,
                                "last_checked_at": datetime.now(timezone.utc).isoformat()
                            }).execute()

                        st.success(f"✅ '{item_name}' 등록이 완료되었습니다!")
                        st.balloons()
                    except Exception as e:
                        st.error(f"❌ 등록 중 오류 발생: {e}")

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
                st.rerun()
            except Exception as e:
                st.error(f"❌ 반영 실패: {e}")