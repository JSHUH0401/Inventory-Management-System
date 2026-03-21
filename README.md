# ☕ 무인 카페 전용 지능형 ERP 시스템 (만월경)

> **"데이터 기반의 재고 관리로 무인 매장의 운영 효율을 극대화합니다."**

본 프로젝트는 **디즈니월드**와 **우아한청년들**에서의 물류 운영 경험을 바탕으로, 무인 카페 매장의 고질적인 문제인 '장부 재고와 실재고의 불일치'를 해결하기 위해 개발되었습니다.

## 🚀 핵심 기능 (Key Features)

### 1. 실시간 재고 모니터링 및 정확도(IRA) 산출
* **IRA(Inventory Record Accuracy)** 지표를 도입하여 시스템의 신뢰도를 시각화합니다.
* **예측 수식:** $$IRA = \max\left(0, 100 - \left(\frac{\sum |실사오차|}{\sum 장부재고} \times 100\right)\right)$$

### 2. 지능형 재고 소모량 학습 알고리즘
* **지수평활법(Exponential Smoothing)**을 적용하여 최신 소모 추세를 실시간으로 반영합니다.
* 요일별 가중치를 고려한 수요 예측 로직을 통해 안전재고 미달 품목을 선제적으로 파악합니다.

### 3. AI 인벤토리 참모 (Gemini Flash 기반)
* **LangChain 에이전트**가 매장 데이터를 분석하여 사장님께 맞춤형 발주 전략을 제안합니다.

## 🛠 Tech Stack
* **Frontend/UI**: Streamlit
* **Backend/DB**: Supabase (PostgreSQL)
* **AI/LLM**: Google Gemini 1.5 Flash
* **Logic**: Python (Pandas, LangChain)

## 📂 프로젝트 구조
* `완성.py`: 메인 서비스 로직 및 UI 렌더링
* `AIAgent.py`: AI 분석 에이전트 핵심 로직
* `StockCalculation.py`: 수요 예측 및 가중치 계산 알고리즘
* `Database.py`: Supabase CRUD 인터페이스
