from datetime import timezone, timedelta

#요일별 가중치를 반영한 품목별 예측 재고 계산
def get_total_weight(start_date, end_date):
    """두 날짜 사이의 요일별 소모 가중치 합계 계산"""
    # 월(0):0.8, 금(4):1.2, 토(5):1.5, 일(6):1.3, 기타:1.0
    weekday_factors = {0: 0.8, 4: 1.2, 5: 1.5, 6: 1.3}
    total_weight = 0
    
    # 시간대 보정 및 계산
    current = start_date.astimezone(timezone.utc) + timedelta(days=1)
    now = end_date.astimezone(timezone.utc)
    
    while current <= now:
        factor = weekday_factors.get(current.weekday(), 1.0)
        total_weight += factor
        current += timedelta(days=1)
    return total_weight