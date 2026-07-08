import streamlit as st
import json
import requests
from io import BytesIO
from PIL import Image
import importlib
import api_service
import llm_service
importlib.reload(api_service)
importlib.reload(llm_service)
from api_service import fetch_product_list, fetch_product_info, search_products
from llm_service import extract_coordi_keywords, generate_try_on_image

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

def main():
    st.title("👗 코디 상품 추천 서비스 프로토타입")
    st.markdown("왼쪽에서 상품을 선택하면, AI가 분석한 맞춤 코디와 실제 추천 상품이 우측에 실시간으로 표시됩니다.")
    st.divider()
    
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
