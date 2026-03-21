import streamlit as st
from Utilities.Database import supabase

def render_order():
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