import streamlit as st
import json
import requests
import base64
from io import BytesIO
from PIL import Image
import importlib
import api_service
import llm_service
importlib.reload(api_service)
importlib.reload(llm_service)
import datetime
from api_service import fetch_product_list, fetch_product_info, search_products
from llm_service import extract_coordi_keywords, generate_try_on_image, generate_context_aware_outfit, generate_outfit_flatlay_image

st.set_page_config(layout="wide", page_title="Coordi Recommendation Prototype")

def load_image_from_url(url):
    try:
        if not url:
            return None
        response = requests.get(url)
        response.raise_for_status()
        return Image.open(BytesIO(response.content))
    except Exception as e:
        return None

def classify_product(prd_nm, keyword=""):
    text = (prd_nm + " " + keyword).lower()
    
    # Bag
    bag_keywords = ["가방", "숄더백", "크로스백", "토트백", "백팩", "핸드백", "클러치백", "에코백", "미니백", "체인백", "쇼퍼백", "클러치", "힙색"]
    is_bag = any(w in text for w in bag_keywords)
    if "백" in text and not is_bag:
        # Exclude common non-bag garment detail keywords that contain "백"
        non_bag = ["백색", "백라인", "백지퍼", "백밴딩", "백포인트", "백멜란지", "백트임", "백기장", "백슬릿", "백버튼"]
        if not any(nb in text for nb in non_bag):
            is_bag = True
            
    if is_bag:
        return "BAG"
    # Shoes
    if any(w in text for w in ["부츠", "구두", "신발", "슈즈", "로퍼", "슬립온", "샌들", "스니커즈", "힐", "워커", "레인부츠"]):
        return "SHOES"
    # Outer
    if any(w in text for w in ["코트", "자켓", "점퍼", "가디건", "아우터", "패딩", "재킷", "레인코트", "바람막이"]):
        return "OUTER"
    # Bottom
    if any(w in text for w in ["팬츠", "슬랙스", "청바지", "데님", "스커트", "치마", "바지", "레깅스"]):
        return "BOTTOM"
    # Top
    if any(w in text for w in ["티셔츠", "셔츠", "블라우스", "니트", "스웨터", "탑", "나시", "원피스", "조끼", "베스트"]):
        return "TOP"
        
    return "ACC"

def render_context_aware_ui():
    opt_col, res_col = st.columns([1, 3])
    
    with opt_col:
        st.subheader("🎛️ 상황 옵션")
        target_date = st.date_input("📅 날짜 선택", datetime.date.today())
        target_date_str = target_date.strftime("%Y-%m-%d")
        
        weather_options = ["맑음 ☀️", "비 🌧️", "흐림 ☁️", "눈 ❄️", "바람/추움 🌬️"]
        
        forecast_dict = api_service.fetch_daily_weather_forecast_seoul()
        
        default_weather_idx = 0
        if target_date_str in forecast_dict:
            auto_weather = forecast_dict[target_date_str]
            auto_weather_str = auto_weather['weather_str']
            st.info(f"📍 일기예보 연동됨 ({auto_weather['temp_min']}°~{auto_weather['temp_max']}°)")
            
            for i, opt in enumerate(weather_options):
                if auto_weather_str in opt:
                    default_weather_idx = i
                    break
        else:
            st.warning("선택한 날짜의 일기예보 정보가 없습니다.")
            
        weather_str = st.selectbox("날씨 (예보 기반 자동세팅, 변경 가능)", weather_options, index=default_weather_idx)
            
        situation_str = st.selectbox("상황(TPO) 선택", ["데일리/캐주얼", "직장/오피스룩", "데이트", "결혼식 하객", "장례식/조문", "면접/미팅", "골프/야외활동", "파티/모임"])
        gender_str = st.selectbox("성별 선택", ["여성 👚", "남성 👕"])
        age_str = st.selectbox("연령대 선택", ["20대", "30대", "40대", "50대", "60대", "70대 이상"], index=1)
        personal_color_str = st.selectbox("퍼스널 컬러", ["선택 안함", "봄 웜톤", "여름 쿨톤", "가을 웜톤", "겨울 쿨톤"])
        style_str = st.selectbox("선호 스타일", ["선택 안함", "미니멀", "스트릿/힙합", "로맨틱/페미닌", "빈티지/아메카지"])
        
        btn = st.button("👗 오늘의 코디 추천받기", use_container_width=True, type="primary")

    if not btn:
        return
        
    with res_col:
        with st.spinner(f"'{weather_str}' 날씨와 '{situation_str}'에 어울리는 코디를 분석 중입니다..."):
            res_str = generate_context_aware_outfit(
                target_date.strftime("%Y년 %m월 %d일"), 
                weather_str, gender_str, age_str, situation_str, personal_color_str, style_str
            )
            
            if res_str:
                try:
                    outfit_data = json.loads(res_str)
                except json.JSONDecodeError:
                    st.error("AI 응답을 파싱하는데 실패했습니다.")
                    return
                
                st.write("---")
                
                # Render Outfit Description (replacing the header)
                st.markdown(f"""
                <div style="padding: 20px; background-color: #f8f9fa; border-radius: 12px; margin-bottom: 20px;">
                    <h3 style="margin-top:0; font-size: 20px; font-weight: bold; color: #333;">✨ {outfit_data.get('theme', '오늘의 코디 추천')}</h3>
                    <p style="margin-bottom:0; font-size: 16px; line-height: 1.6; color: #555;">{outfit_data.get('description', '')}</p>
                </div>
                """, unsafe_allow_html=True)
                
                components = outfit_data.get("components", [])
                matched_products = []
                component_images = []
                
                fetch_status = st.empty()
                with fetch_status.container():
                    st.info("코디 구성 상품을 검색하고 있습니다...")
                
                for comp in components:
                    s_keyword = comp.get("search_keyword", "")
                    gnd = comp.get("gnd_cd", "")
                    c_level = comp.get("category_level", "")
                    c_code = comp.get("category_code", "")
                    
                    # Fallback configurations: try broad keyword first, then relax category filters
                    keywords_to_try = [s_keyword]
                    if len(s_keyword.split()) > 1:
                        keywords_to_try.append(s_keyword.split()[-1]) # e.g. "슬랙스" from "핀턱 슬랙스"
                    
                    search_configs = []
                    for kw in keywords_to_try:
                        search_configs.append({"kw": kw, "lvl": c_level, "code": c_code})
                    for kw in keywords_to_try:
                        search_configs.append({"kw": kw, "lvl": c_level, "code": ""}) # relax category code
                    
                    matched = False
                    for cfg in search_configs:
                        search_res = search_products(
                            keyword=cfg["kw"],
                            gnd_cd=gnd,
                            cat_level=cfg["lvl"],
                            cat_code=cfg["code"]
                        )
                        
                        if search_res:
                            candidates = []
                            for sp in search_res:
                                source = sp.get('_source', {})
                                gnd_list = source.get('gndCd', [])
                                if "01" in gnd_list and "02" in gnd_list and "03" in gnd_list:
                                    continue
                                if source.get('appPrdImgUrl'):
                                    candidates.append(source)
                                    
                            # Shuffle the top 5 candidates to guarantee diversity while preserving relevance
                            import random
                            top_candidates = candidates[:5]
                            random.shuffle(top_candidates)
                            all_candidates = top_candidates + candidates[5:]
                            
                            for candidate in all_candidates:
                                img_url = candidate.get('appPrdImgUrl', '')
                                img = load_image_from_url(img_url)
                                if img:
                                    candidate['matched_keyword'] = s_keyword
                                    matched_products.append(candidate)
                                    component_images.append(img)
                                    matched = True
                                    break
                            if matched:
                                break
                                
                fetch_status.empty()
                
                if not matched_products:
                    st.warning("추천 코디에 해당하는 상품을 찾지 못했습니다.")
                    return
                    
                has_bag = any(classify_product(p.get('prdNm', ''), p.get('matched_keyword', '')) == "BAG" for p in matched_products)
                has_outer = any(classify_product(p.get('prdNm', ''), p.get('matched_keyword', '')) == "OUTER" for p in matched_products)
                
                prd_names = [p.get('prdNm', '') for p in matched_products]
                with st.spinner("최고의 패션 매거진 화보(코디 샷)를 생성 중입니다... (약 15~30초 소요)"):
                    flatlay_img = generate_outfit_flatlay_image(component_images, weather_str, prd_names, has_bag, has_outer)
                    
                # Layout: Split into Left (Image) and Right (Products & Description)
                res_col_left, res_col_right = st.columns([4, 5])
                
                with res_col_left:
                    if flatlay_img:
                        if flatlay_img.mode in ("RGBA", "P"):
                            flatlay_img = flatlay_img.convert("RGB")
                        buffered = BytesIO()
                        flatlay_img.save(buffered, format="JPEG")
                        img_b64 = base64.b64encode(buffered.getvalue()).decode()
                        
                        class_coords = {
                            "TOP": ("right", 0.5, 30),
                            "BOTTOM": ("left", 0.5, 60),
                            "SHOES": ("right", 0.5, 88),
                        }
                        tags_overlay_html = ""
                        used_coords = []
                        side_count = 0
                        
                        # Run vision locator to get exact coordinates of each item in the generated image
                        detected_coords = {}
                        try:
                            keywords_list = [f"{idx}_{prod.get('matched_keyword', '').split()[-1] if prod.get('matched_keyword', '') else '아이템'}" for idx, prod in enumerate(matched_products)]
                            with st.spinner("해시태그 위치 정밀 조율 중..."):
                                detected_coords = llm_service.detect_item_coordinates(flatlay_img, keywords_list)
                        except Exception as ex:
                            print(f"Vision coordinate detection failed: {ex}")
                        
                        for idx, prod in enumerate(matched_products):
                            keyword = prod.get('matched_keyword', '')
                            prd_nm = prod.get('prdNm', '')
                            category = classify_product(prd_nm, keyword)
                            tag_word = keyword.split()[-1] if keyword else '아이템'
                            
                            # Check if Vision AI found coordinates
                            num_kw = f"{idx}_{tag_word}"
                            coord_data = detected_coords.get(num_kw) if detected_coords else None
                            if coord_data and isinstance(coord_data, dict) and "x" in coord_data and "y" in coord_data:
                                rx = float(coord_data["x"]) / 100.0
                                ry = float(coord_data["y"])
                                side = "left" if rx < 0.5 else "right"
                            else:
                                # Fallback Heuristics
                                if category in class_coords:
                                    side, rx, ry = class_coords[category]
                                else:
                                    # Spatially balance side items (first goes right, second left, etc.)
                                    if side_count % 2 == 0:
                                        side, rx = "right", 0.75
                                    else:
                                        side, rx = "left", 0.25
                                        
                                    if category == "OUTER" or category == "BAG":
                                        ry = 45
                                    else: # ACC
                                        ry = 25
                                    side_count += 1
                            
                            # Avoid overlap on y-axis
                            while any(abs(c[2] - ry) < 6 and c[0] == side for c in used_coords):
                                ry += 8
                                
                            used_coords.append((side, rx, ry))
                            
                            tag_word = keyword.split()[-1] if keyword else '아이템'
                            prd_link = f"https://www.halfclub.com/product/{prod.get('prdNo', '')}"
                            
                            # Dot position on the image (0% to 100%)
                            dot_left = f"{rx * 100}%"
                            dot_top = f"{ry}%"
                            
                            # Render Dot (Red dot with white border and shadow)
                            tags_overlay_html += f'<div style="position: absolute; top: {dot_top}; left: {dot_left}; width: 8px; height: 8px; border-radius: 50%; background-color: #ff4b4b; border: 2px solid white; box-shadow: 0 1px 3px rgba(0,0,0,0.3); transform: translate(-50%, -50%); z-index: 10;"></div>\n'
                            
                            # Render Line and Tag inside the container (no padding)
                            tag_width = 80
                            tag_margin = 15
                            tag_end = tag_margin + tag_width # 95px
                            
                            if side == "left":
                                tag_style = f"position: absolute; top: {ry}%; left: {tag_margin}px; width: {tag_width}px; height: 28px; line-height: 25px; text-align: center; background-color: white; color: #ff4b4b; border-radius: 20px; font-size: 12px; font-weight: bold; text-decoration: none; box-shadow: 0 2px 8px rgba(255, 75, 75, 0.2); border: 1.5px solid #ff4b4b; z-index: 10; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; display: block; transform: translateY(-50%);"
                                line_style = f"position: absolute; top: {ry}%; left: {tag_end}px; width: calc({dot_left} - {tag_end}px); height: 0px; border-top: 1.5px dashed #ff4b4b; transform: translateY(-50%); z-index: 5;"
                            else: # right
                                tag_style = f"position: absolute; top: {ry}%; right: {tag_margin}px; width: {tag_width}px; height: 28px; line-height: 25px; text-align: center; background-color: white; color: #ff4b4b; border-radius: 20px; font-size: 12px; font-weight: bold; text-decoration: none; box-shadow: 0 2px 8px rgba(255, 75, 75, 0.2); border: 1.5px solid #ff4b4b; z-index: 10; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; display: block; transform: translateY(-50%);"
                                line_style = f"position: absolute; top: {ry}%; left: {dot_left}; width: calc(100% - {tag_end}px - {dot_left}); height: 0px; border-top: 1.5px dashed #ff4b4b; transform: translateY(-50%); z-index: 5;"
                            
                            tags_overlay_html += f'<a href="{prd_link}" target="_blank" style="{tag_style}">#{tag_word}</a>\n'
                            tags_overlay_html += f'<div style="{line_style}"></div>\n'
                        
                        html_code = f'<div style="position: relative; width: 100%; overflow: hidden; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);"><img src="data:image/jpeg;base64,{img_b64}" style="width: 100%; display: block;" />{tags_overlay_html}</div>'
                        st.markdown(html_code, unsafe_allow_html=True)
                        
                    tags = outfit_data.get("tags", [])
                    if tags:
                        tags_html = "".join([f"<span style='display:inline-block; padding: 5px 12px; background-color:#f0f0f0; border-radius:20px; font-size:13px; color:#555; margin-right:8px; margin-top:15px;'>{t}</span>" for t in tags])
                        st.markdown(f"<div>{tags_html}</div>", unsafe_allow_html=True)
                
                with res_col_right:
                    st.write("### 🛍️ 코디 구성 상품")
                    cols = st.columns(len(matched_products))
                    for idx, prod in enumerate(matched_products):
                        with cols[idx]:
                            img_url = prod.get('appPrdImgUrl', '')
                            prd_no = prod.get('prdNo', '')
                            prd_nm = prod.get('prdNm', '')
                            brand_nm = prod.get('brandNm', '')
                            price = prod.get('dcPrcApp', 0)
                            
                            prd_link = f"https://www.halfclub.com/product/{prd_no}"
                            
                            if img_url:
                                st.markdown(
                                    f'<a href="{prd_link}" target="_blank">'
                                    f'  <img src="{img_url}" style="width:100%; border-radius:8px; aspect-ratio:3/4; object-fit:cover; margin-bottom:8px; border:1px solid #eee;">'
                                    f'</a>',
                                    unsafe_allow_html=True
                                )
                            st.caption(f"**[{brand_nm}]**")
                            st.markdown(f"<a href='{prd_link}' target='_blank' style='text-decoration:none; color:inherit;'><p style='font-size:12px; margin-bottom:2px; height:36px; overflow:hidden;'>{prd_nm}</p></a>", unsafe_allow_html=True)
                            st.markdown(f"<span style='color:#ff4b4b; font-weight:bold;'>₩{price:,}</span>", unsafe_allow_html=True)
                            st.markdown(f"<a href='{prd_link}' target='_blank' style='display:block; text-align:center; padding:6px 0; margin-top:10px; background-color:#333; color:white; border-radius:4px; font-size:12px; text-decoration:none; font-weight:bold;'>상세보기</a>", unsafe_allow_html=True)
            else:
                st.error("AI가 코디를 추천하지 못했습니다.")

def render_manual_coordination_ui():
    # Initialize session state for manual selected items
    if "manual_selected_items" not in st.session_state:
        st.session_state.manual_selected_items = []
    if "manual_flatlay_img" not in st.session_state:
        st.session_state.manual_flatlay_img = None
    if "manual_detected_coords" not in st.session_state:
        st.session_state.manual_detected_coords = {}
        
    opt_col, res_col = st.columns([4, 5])
    
    with opt_col:
        st.subheader("🛍️ 선택된 코디 상품 목록")
        selected_count = len(st.session_state.manual_selected_items)
        st.caption(f"현재 선택된 상품: **{selected_count} / 6** (최소 2개 이상 선택해야 화보 완성이 가능합니다)")
        
        if selected_count > 0:
            cols = st.columns(6)
            for idx, prod in enumerate(st.session_state.manual_selected_items):
                prd_nm = prod.get('prdNm', '상품')
                img_url = prod.get('appPrdImgUrl', '')
                with cols[idx]:
                    if img_url:
                        st.image(img_url, use_container_width=True)
                    st.caption(prd_nm[:10] + "..." if len(prd_nm) > 10 else prd_nm)
                    if st.button("❌", key=f"del_{idx}_{prod.get('prdNo')}", help="코디에서 제거"):
                        st.session_state.manual_selected_items.pop(idx)
                        st.session_state.manual_flatlay_img = None  # Reset generated image
                        st.session_state.manual_detected_coords = {}
                        st.rerun()
        else:
            st.info("아래 검색결과에서 상품을 찾아 ➕ 버튼을 클릭해 코디 상품으로 추가하세요.")
            
        st.divider()
        st.subheader("🔍 상품 검색")
        search_query = st.text_input("검색할 키워드를 입력하세요", placeholder="예: 블라우스, 슬랙스, 자켓, 가방, 로퍼", key="manual_search_query")
        
        if search_query:
            with st.spinner("상품을 검색 중입니다..."):
                search_results = search_products(search_query)
                
            if search_results:
                st.write(f"검색 결과: **{len(search_results)}**개")
                grid_cols = st.columns(3)
                for s_idx, sp in enumerate(search_results):
                    source = sp.get('_source', {})
                    prd_no = source.get('prdNo')
                    prd_nm = source.get('prdNm')
                    brand_nm = source.get('brandNm')
                    price = source.get('dcPrcApp', 0)
                    img_url = source.get('appPrdImgUrl')
                    
                    with grid_cols[s_idx % 3]:
                        if img_url:
                            st.image(img_url, use_container_width=True)
                        st.markdown(f"**[{brand_nm}]** {prd_nm[:25]}...")
                        st.markdown(f"<span style='color:#ff4b4b; font-weight:bold;'>₩{price:,}</span>", unsafe_allow_html=True)
                        
                        # Check if already added
                        is_added = any(p.get('prdNo') == prd_no for p in st.session_state.manual_selected_items)
                        category_to_add = classify_product(prd_nm, search_query)
                        category_exists = any(
                            classify_product(p.get('prdNm', ''), p.get('matched_keyword', '')) == category_to_add 
                            for p in st.session_state.manual_selected_items
                        )
                        
                        if is_added:
                            st.button("추가됨 ✔️", key=f"add_{prd_no}", disabled=True, use_container_width=True)
                        elif category_exists:
                            cat_korean = {
                                "TOP": "상의",
                                "BOTTOM": "하의",
                                "OUTER": "아우터",
                                "BAG": "가방",
                                "SHOES": "신발",
                                "ACC": "액세서리"
                            }.get(category_to_add, "기타")
                            st.button(f"{cat_korean} 추가됨 🚫", key=f"add_{prd_no}", disabled=True, use_container_width=True, help="코디에는 동일한 종류의 상품을 중복하여 등록할 수 없습니다.")
                        else:
                            disable_add = selected_count >= 6
                            if st.button("➕ 코디 추가", key=f"add_{prd_no}", disabled=disable_add, use_container_width=True):
                                # Set match keyword from search query to categorize correctly
                                source['matched_keyword'] = search_query
                                st.session_state.manual_selected_items.append(source)
                                st.session_state.manual_flatlay_img = None  # Reset generated image
                                st.session_state.manual_detected_coords = {}
                                st.rerun()
            else:
                st.warning("검색 결과가 없습니다.")
                
    with res_col:
        st.subheader("📸 코디 완성 화보")
        weather_options = ["맑음 ☀️", "비 🌧️", "흐림 ☁️", "눈 ❄️", "바람/추움 🌬️"]
        weather_str = st.selectbox("배경 날씨/상황 선택", weather_options, key="manual_weather")
        
        btn_enabled = selected_count >= 2
        generate_btn = st.button("✨ 코디 완성하기 (AI 화보 생성)", use_container_width=True, type="primary", disabled=not btn_enabled)
        
        if generate_btn:
            component_images = []
            matched_products = []
            
            with st.spinner("상품 이미지를 불러오는 중입니다..."):
                for prod in st.session_state.manual_selected_items:
                    img_url = prod.get('appPrdImgUrl', '')
                    if img_url:
                        img = load_image_from_url(img_url)
                        if img:
                            component_images.append(img)
                            matched_products.append(prod)
                            
            if not component_images:
                st.error("선택한 상품의 이미지를 불러오지 못했습니다.")
                return
                
            has_bag = any(classify_product(p.get('prdNm', ''), p.get('matched_keyword', '')) == "BAG" for p in matched_products)
            has_outer = any(classify_product(p.get('prdNm', ''), p.get('matched_keyword', '')) == "OUTER" for p in matched_products)
            prd_names = [p.get('prdNm', '') for p in matched_products]
            
            with st.spinner("최고의 패션 매거진 화보(코디 샷)를 생성 중입니다... (약 15~30초 소요)"):
                flatlay_img = generate_outfit_flatlay_image(component_images, weather_str, prd_names, has_bag, has_outer)
                
            if flatlay_img:
                st.session_state.manual_flatlay_img = flatlay_img
                # Run vision locator to get exact coordinates
                keywords_list = [f"{idx}_{p.get('matched_keyword', '').split()[-1] if p.get('matched_keyword', '') else '아이템'}" for idx, p in enumerate(matched_products)]
                with st.spinner("해시태그 위치 정밀 조율 중..."):
                    detected_coords = llm_service.detect_item_coordinates(flatlay_img, keywords_list)
                    st.session_state.manual_detected_coords = detected_coords
            else:
                st.error("화보 생성에 실패했습니다.")
                
        # Render current flatlay and hashtags if they exist
        if st.session_state.manual_flatlay_img is not None:
            flatlay_img = st.session_state.manual_flatlay_img
            detected_coords = st.session_state.manual_detected_coords
            matched_products = st.session_state.manual_selected_items
            
            if flatlay_img.mode in ("RGBA", "P"):
                flatlay_img = flatlay_img.convert("RGB")
            buffered = BytesIO()
            flatlay_img.save(buffered, format="JPEG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode()
            
            class_coords = {
                "TOP": ("right", 0.5, 30),
                "BOTTOM": ("left", 0.5, 60),
                "SHOES": ("right", 0.5, 88),
            }
            tags_overlay_html = ""
            used_coords = []
            side_count = 0
            
            for idx, prod in enumerate(matched_products):
                keyword = prod.get('matched_keyword', '')
                prd_nm = prod.get('prdNm', '')
                category = classify_product(prd_nm, keyword)
                tag_word = keyword.split()[-1] if keyword else '아이템'
                prd_link = f"https://www.halfclub.com/product/{prod.get('prdNo', '')}"
                
                num_kw = f"{idx}_{tag_word}"
                coord_data = detected_coords.get(num_kw) if detected_coords else None
                if coord_data and isinstance(coord_data, dict) and "x" in coord_data and "y" in coord_data:
                    rx = float(coord_data["x"]) / 100.0
                    ry = float(coord_data["y"])
                    side = "left" if rx < 0.5 else "right"
                else:
                    if category in class_coords:
                        side, rx, ry = class_coords[category]
                    else:
                        if side_count % 2 == 0:
                            side, rx = "right", 0.75
                        else:
                            side, rx = "left", 0.25
                        if category == "OUTER" or category == "BAG":
                            ry = 45
                        else:
                            ry = 25
                        side_count += 1
                        
                while any(abs(c[2] - ry) < 6 and c[0] == side for c in used_coords):
                    ry += 8
                used_coords.append((side, rx, ry))
                
                dot_left = f"{rx * 100}%"
                dot_top = f"{ry}%"
                
                tags_overlay_html += f'<div style="position: absolute; top: {dot_top}; left: {dot_left}; width: 8px; height: 8px; border-radius: 50%; background-color: #ff4b4b; border: 2px solid white; box-shadow: 0 1px 3px rgba(0,0,0,0.3); transform: translate(-50%, -50%); z-index: 10;"></div>\n'
                
                tag_width = 80
                tag_margin = 15
                tag_end = tag_margin + tag_width # 95px
                
                if side == "left":
                    tag_style = f"position: absolute; top: {ry}%; left: {tag_margin}px; width: {tag_width}px; height: 28px; line-height: 25px; text-align: center; background-color: white; color: #ff4b4b; border-radius: 20px; font-size: 12px; font-weight: bold; text-decoration: none; box-shadow: 0 2px 8px rgba(255, 75, 75, 0.2); border: 1.5px solid #ff4b4b; z-index: 10; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; display: block; transform: translateY(-50%);"
                    line_style = f"position: absolute; top: {ry}%; left: {tag_end}px; width: calc({dot_left} - {tag_end}px); height: 0px; border-top: 1.5px dashed #ff4b4b; transform: translateY(-50%); z-index: 5;"
                else: # right
                    tag_style = f"position: absolute; top: {ry}%; right: {tag_margin}px; width: {tag_width}px; height: 28px; line-height: 25px; text-align: center; background-color: white; color: #ff4b4b; border-radius: 20px; font-size: 12px; font-weight: bold; text-decoration: none; box-shadow: 0 2px 8px rgba(255, 75, 75, 0.2); border: 1.5px solid #ff4b4b; z-index: 10; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; display: block; transform: translateY(-50%);"
                    line_style = f"position: absolute; top: {ry}%; left: {dot_left}; width: calc(100% - {tag_end}px - {dot_left}); height: 0px; border-top: 1.5px dashed #ff4b4b; transform: translateY(-50%); z-index: 5;"
                
                tags_overlay_html += f'<a href="{prd_link}" target="_blank" style="{tag_style}">#{tag_word}</a>\n'
                tags_overlay_html += f'<div style="{line_style}"></div>\n'
                
            html_content = f'<div style="position: relative; width: 100%; overflow: hidden; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);"><img src="data:image/jpeg;base64,{img_b64}" style="width: 100%; display: block;" />{tags_overlay_html}</div>'
            st.markdown(html_content, unsafe_allow_html=True)
            
            # Display selected products list with details below the image
            st.divider()
            st.subheader("🛍️ 코디 상품 정보")
            for prod in matched_products:
                prd_no = prod.get('prdNo')
                prd_nm = prod.get('prdNm')
                brand_nm = prod.get('brandNm')
                price = prod.get('dcPrcApp', 0)
                prd_link = f"https://www.halfclub.com/product/{prd_no}"
                
                col1, col2 = st.columns([1, 4])
                with col1:
                    img_url = prod.get('appPrdImgUrl', '')
                    if img_url:
                        st.image(img_url, use_container_width=True)
                with col2:
                    st.markdown(f"**[{brand_nm}]** {prd_nm}")
                    st.markdown(f"<span style='color:#ff4b4b; font-weight:bold;'>₩{price:,}</span>", unsafe_allow_html=True)
                    st.markdown(f"<a href='{prd_link}' target='_blank' style='display:inline-block; padding:4px 12px; background-color:#333; color:white; border-radius:4px; font-size:11px; text-decoration:none; font-weight:bold;'>상세보기</a>", unsafe_allow_html=True)
                st.write("")

def main():
    st.title("👗 코디 상품 추천 서비스")
    st.markdown("왼쪽에서 상품을 선택하면, AI가 분석한 맞춤 코디와 실제 추천 상품이 우측에 실시간으로 표시됩니다.")
    
    # Mode selector
    mode = st.radio(
        "🛠️ 작동 모드 선택", 
        ["🌟 AI 상황 맞춤 자동 코디 추천", "🎨 내 맘대로 수동 코디 조합 (최대 6개)", "👕 단품 기준 AI 추천 & 가상 착장"], 
        horizontal=True
    )
    st.divider()
    
    if mode == "🌟 AI 상황 맞춤 자동 코디 추천":
        render_context_aware_ui()
        return
        
    elif mode == "🎨 내 맘대로 수동 코디 조합 (최대 6개)":
        render_manual_coordination_ui()
        return
    
    if "selected_product" not in st.session_state:
        st.session_state.selected_product = None
    if "coordi_results" not in st.session_state:
        st.session_state.coordi_results = None
    if "try_on_result" not in st.session_state:
        st.session_state.try_on_result = None
    if "try_on_cloth" not in st.session_state:
        st.session_state.try_on_cloth = None

    # Layout: Split screen into Left (Product List) and Right (Coordi Results)
    col_left, col_right = st.columns([4, 5])
    
    # ------------------ LEFT SIDE: Product List ------------------
    with col_left:
        st.subheader("👕 기준 상품 선택")
        with st.spinner("상품 리스트를 불러오는 중입니다..."):
            products = fetch_product_list()
        
        if products:
            # Display products in a compact grid (3 columns inside the split layout makes images smaller)
            sub_cols = st.columns(3)
            for idx, p in enumerate(products[:18]): # Show 18 items
                source = p.get('_source', {})
                prd_no = source.get('prdNo')
                prd_nm = source.get('prdNm')
                brand_nm = source.get('brandNm')
                price = source.get('dcPrcApp', 0)
                img_url = source.get('appPrdImgUrl')
                
                with sub_cols[idx % 3]:
                    if img_url:
                        st.markdown(
                            f'<a href="https://www.halfclub.com/product/{prd_no}" target="_blank">'
                            f'  <img src="{img_url}" style="width:100%; border-radius:8px; aspect-ratio:3/4; object-fit:cover; margin-bottom:8px; border:1px solid #eee; cursor:pointer;" title="새창으로 상세 상품 보기">'
                            f'</a>',
                            unsafe_allow_html=True
                        )
                    st.markdown(f"<span style='font-size:12px; font-weight:bold; color:#555;'>[{brand_nm}]</span>", unsafe_allow_html=True)
                    st.markdown(f"<p style='font-size:11px; margin-bottom:2px; height:36px; overflow:hidden; line-height:1.2;'>{prd_nm}</p>", unsafe_allow_html=True)
                    st.markdown(f"<span style='font-size:12px; color:#ff4b4b; font-weight:bold;'>₩{price:,}</span>", unsafe_allow_html=True)
                    if st.button("선택", key=f"sel_{prd_no}", use_container_width=True):
                        st.session_state.selected_product = source
                        st.session_state.coordi_results = None
                        st.session_state.try_on_result = None
                        st.session_state.try_on_cloth = None
                        st.rerun()
                        
    # ------------------ RIGHT SIDE: Coordi Results ------------------
    with col_right:
        if st.session_state.selected_product is None:
            st.info("👈 왼쪽 상품 리스트에서 코디를 추천받을 상품의 [선택] 버튼을 클릭해 주세요.")
        else:
            main_p = st.session_state.selected_product
            prd_no = main_p.get('prdNo')
            prd_nm = main_p.get('prdNm')
            brand_nm = main_p.get('brandNm')
            brand_cd = main_p.get('brandCd')
            img_url = main_p.get('appPrdImgUrl')
            
            # Extract metadata
            gender_cat = main_p.get('dpCtgrNm1', '')
            category = f"{gender_cat} > {main_p.get('dpCtgrNm2', '')} > {main_p.get('dpCtgrNm3', '')}"
            tags = main_p.get('prdTag', '')
            material = main_p.get('AT113', '')
            color = main_p.get('colorCd', '')
            season = main_p.get('prdKeyword', '')
            
            st.subheader("🎯 선택된 기준 상품")
            detail_col1, detail_col2 = st.columns([1, 2])
            with detail_col1:
                if img_url:
                    st.markdown(
                        f'<a href="https://www.halfclub.com/product/{prd_no}" target="_blank">'
                        f'  <img src="{img_url}" style="width:100%; border-radius:8px; aspect-ratio:3/4; object-fit:cover; border:1px solid #eee; cursor:pointer;" title="새창으로 상세 상품 보기">'
                        f'</a>',
                        unsafe_allow_html=True
                    )
            with detail_col2:
                st.markdown(f"#### **[{brand_nm}]** {prd_nm}")
                st.caption(f"**카테고리**: {category}")
                st.caption(f"**시즌/키워드**: {season}")
                st.caption(f"**속성**: {tags} / {material} / {color}")
                st.caption(f"**브랜드코드**: {brand_cd}")
            
            st.divider()
            st.subheader("🧥 AI 맞춤 코디 추천 결과 (필터 검색 적용)")
            
            if st.session_state.coordi_results is None:
                with st.spinner("상품 정보를 분석하고 어울리는 코디 아이템을 찾는 중입니다..."):
                    # 1. Fetch details
                    detail_info = fetch_product_info(prd_no)
                    
                    # 2. Build prompt
                    info_for_llm = f"Brand Name: {brand_nm}\nBrand Code (brandCd): {brand_cd}\nProduct Name: {prd_nm}\n"
                    info_for_llm += f"Category (Gender): {category}\n"
                    info_for_llm += f"Season & Keywords: {season}\n"
                    info_for_llm += f"Attributes: Tags({tags}), Material({material}), Color({color})\n"
                    
                    if detail_info and 'data' in detail_info:
                        desc = detail_info['data'].get('prdDesc', '')
                        if desc:
                            info_for_llm += f"Description Snippet: {desc[:300]}...\n"
                    
                    # 3. Get image
                    img = load_image_from_url(img_url)
                    
                    # 4. Call LLM
                    coordi_json_str = extract_coordi_keywords(info_for_llm, img)
                    
                    if coordi_json_str:
                        try:
                            st.session_state.coordi_results = json.loads(coordi_json_str)
                            st.rerun()
                        except json.JSONDecodeError:
                            st.error("AI 응답을 파싱하는데 실패했습니다.")
                            st.session_state.coordi_results = {"recommendations": []}
                    else:
                        st.error("AI 코디 추천에 실패했습니다.")
                        st.session_state.coordi_results = {"recommendations": []}
            else:
                recs = st.session_state.coordi_results.get("recommendations", [])
                
                if not recs:
                    st.warning("추천 결과가 없습니다.")
                else:
                    tabs = st.tabs([f"{rec['category']}" for rec in recs])
                    
                    for idx, rec in enumerate(recs):
                        with tabs[idx]:
                            st.info(f"💡 **추천 이유:** {rec['reason']}")
                            
                            # Show applied filters visually
                            filter_details = []
                            if rec.get('gnd_cd'):
                                gender_name = "남성" if rec['gnd_cd'] == "01" else "여성" if rec['gnd_cd'] == "02" else "공용"
                                filter_details.append(f"성별: {gender_name} ({rec['gnd_cd']})")
                            if rec.get('brand_cd'):
                                filter_details.append(f"브랜드코드: {rec['brand_cd']}")
                            if rec.get('category_code'):
                                filter_details.append(f"카테고리코드: {rec['category_code']} ({rec['category_level']})")
                                
                            with st.expander("⚙️ 자동 적용된 검색 필터 (클릭해서 펼치기)", expanded=False):
                                for f_item in filter_details:
                                    st.markdown(f"- `{f_item}`")
                                
                            st.success(f"🔍 **검색 키워드 (속성):** {rec['search_keyword']}")
                            
                            # Search with filters
                            with st.spinner(f"'{rec['search_keyword']}' 검색 중..."):
                                search_res = search_products(
                                    keyword=rec['search_keyword'],
                                    gnd_cd=rec.get('gnd_cd'),
                                    brand_cd=rec.get('brand_cd'),
                                    cat_level=rec.get('category_level'),
                                    cat_code=rec.get('category_code')
                                )
                                
                            if search_res:
                                st.write("✅ **필터 및 키워드가 매칭된 실시간 추천 상품:**")
                                s_cols = st.columns(3)
                                
                                # Filter out multi-gender generic items
                                filtered_res = []
                                for sp in search_res:
                                    s_source = sp.get('_source', {})
                                    gnd_list = s_source.get('gndCd', [])
                                    if "01" in gnd_list and "02" in gnd_list and "03" in gnd_list:
                                        continue
                                    filtered_res.append(sp)
                                    
                                for s_idx, sp in enumerate(filtered_res[:6]): 
                                    s_source = sp.get('_source', {})
                                    s_prd_no = s_source.get('prdNo')
                                    with s_cols[s_idx % 3]:
                                        s_img_url = s_source.get('appPrdImgUrl', '')
                                        if s_img_url:
                                            st.markdown(
                                                f'<a href="https://www.halfclub.com/product/{s_prd_no}" target="_blank">'
                                                f'  <img src="{s_img_url}" style="width:100%; border-radius:8px; aspect-ratio:3/4; object-fit:cover; margin-bottom:8px; border:1px solid #eee; cursor:pointer;" title="새창으로 상세 상품 보기">'
                                                f'</a>',
                                                unsafe_allow_html=True
                                            )
                                        st.caption(f"[{s_source.get('brandNm', '')}] {s_source.get('prdNm', '')}")
                                        price = s_source.get('dcPrcApp', 0)
                                        st.write(f"₩{price:,}")
                                        if st.button("✨ 가상 착장", key=f"try_{s_prd_no}", use_container_width=True):
                                            with st.spinner("상품 정보를 상세 조회 중입니다..."):
                                                s_details = fetch_product_info(s_prd_no)
                                                
                                            add_img_urls = []
                                            if s_details and "data" in s_details and s_details["data"]:
                                                prod_img_dict = s_details["data"].get("productImage", {})
                                                if prod_img_dict:
                                                    for i in range(1, 10):
                                                        field_name = f"add{i}ExtNm"
                                                        relative_path = prod_img_dict.get(field_name)
                                                        if relative_path:
                                                            if not relative_path.startswith("http"):
                                                                full_url = f"https://cdn2.halfclub.com/{relative_path}"
                                                            else:
                                                                full_url = relative_path
                                                            add_img_urls.append(full_url)
                                            
                                            # Layered try-on check: layer on top of previous result if it is a 3:4 try-on image
                                            base_model = img_url
                                            if st.session_state.try_on_result is not None:
                                                w, h = st.session_state.try_on_result.size
                                                if w < h: # Width < Height implies a 3:4 portrait try-on result
                                                    base_model = st.session_state.try_on_result
                                                    
                                            with st.spinner("AI 가상 착장 이미지를 생성 중입니다... (약 15~30초 소요)"):
                                                result_img = generate_try_on_image(
                                                    base_model, 
                                                    s_img_url, 
                                                    category_name=rec['category'], 
                                                    add_img_urls=add_img_urls
                                                )
                                                if result_img:
                                                    st.session_state.try_on_result = result_img
                                                    st.session_state.try_on_cloth = s_source
                                                    st.rerun()
                            else:
                                st.warning(f"적용된 필터 및 키워드 '{rec['search_keyword']}'에 대한 검색 결과가 없습니다.")
                                
            # Render VTON try-on result if exists
            if st.session_state.try_on_result is not None:
                st.write("---")
                width, height = st.session_state.try_on_result.size
                is_try_on = width < height
                
                if is_try_on:
                    st.subheader("🖼️ 가상 착장 결과 (AI Try-on)")
                    try_col1, try_col2 = st.columns(2)
                    with try_col1:
                        st.write("👉 **기준 상품 모델**")
                        if img_url:
                            st.image(img_url, use_container_width=True)
                    with try_col2:
                        cloth_name = st.session_state.try_on_cloth.get('prdNm', '') if st.session_state.try_on_cloth else '코디 추천 상품'
                        st.write(f"✨ **착장 완료 (아이템: {cloth_name})**")
                        st.image(st.session_state.try_on_result, use_container_width=True)
                else:
                    st.subheader("🖼️ 스타일링 코디 보드 (Styling Lookbook)")
                    cloth_name = st.session_state.try_on_cloth.get('prdNm', '') if st.session_state.try_on_cloth else '코디 추천 상품'
                    st.caption(f"기준 상품과 **[{cloth_name}]**의 실제 원본 이미지를 화질 저하나 왜곡(환각 현상) 없이 결합하여 매칭한 스타일링 룩북입니다.")
                    st.image(st.session_state.try_on_result, use_container_width=True)
                
                if st.button("🔄 가상 착장 초기화 (리셋)", use_container_width=True):
                    st.session_state.try_on_result = None
                    st.session_state.try_on_cloth = None
                    st.rerun()

if __name__ == "__main__":
    main()
