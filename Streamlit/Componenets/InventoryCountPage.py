import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
from Utilities.Database import supabase
from Utilities.StockCalculation import get_total_weight

#재고실사 페이지
def render_inventorycount():
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
