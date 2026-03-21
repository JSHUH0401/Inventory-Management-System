import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from Utilities.Database import supabase

def render_admin():
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