import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps
import time

def call_gemini_with_retry(client, model, contents, config=None, retries=4, delay=2):
    for i in range(retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config
            )
            return response
        except Exception as e:
            e_str = str(e)
            if "503" in e_str or "429" in e_str or "high demand" in e_str or "UNAVAILABLE" in e_str or "RESOURCE_EXHAUSTED" in e_str:
                if i < retries - 1:
                    time.sleep(delay * (2 ** i))
                    continue
            raise e

class CoordiRecommendation(BaseModel):
    category: str = Field(description="추천하는 코디 상품의 품목 카테고리 (예: 바지, 신발, 가방, 아우터)")
    gnd_cd: str = Field(description="추천 상품의 성별 필터 코드. 남성은 '01', 여성은 '02', 남녀공용은 '03' 필수 입력.")
    brand_cd: str = Field(description="추천 상품의 브랜드 코드. 추천 상품의 브랜드는 기준 상품과 상관없으므로 항상 빈 문자열(\"\")로 비워두어야 합니다.")
    category_level: str = Field(description="카테고리 필터 레벨. 카테고리 매핑 정보와 일치할 시 'dpCtgrNo2' 또는 'dpCtgrNo3'를 입력하며, 일치하지 않으면 빈 문자열(\"\")을 입력합니다.")
    category_code: str = Field(description="제공된 카테고리 매핑 목록 중 해당하는 카테고리 번호. 해당하는 정보가 없으면 빈 문자열(\"\")로 채웁니다.")
    search_keyword: str = Field(description="검색 쿼리 키워드. 카테고리, 성별, 브랜드 필터로 적용된 명칭(예: 바지, 스커트, 남성, 여성, 브랜드명 등)을 절대 포함하지 마세요. 대신 필터링할 수 없는 순수 스타일링 속성(예: '린넨 와이드', '체크', '스트라이프', '스트레치', '오버핏 린넨')만 작성해야 합니다.")
    reason: str = Field(description="이 추천 상품이 기준 상품과 스타일링적으로 어떻게 어울리는지에 대한 상세한 코디 추천 이유. 반드시 존댓말 한글로 작성합니다.")

class CoordiResponse(BaseModel):
    recommendations: list[CoordiRecommendation]

def extract_coordi_keywords(product_info, image=None):
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    
    category_mapping_prompt = """
    Available Categories for Filtering (category_level & category_code):
    - 여성 원피스: dpCtgrNo2 = 32509
    - 여성 가디건: dpCtgrNo2 = 32538
    - 여성 니트/스웨터: dpCtgrNo2 = 32548
    - 여성 셔츠/블라우스: dpCtgrNo2 = 32558
    - 여성 티셔츠: dpCtgrNo2 = 32510
    - 여성 스커트: dpCtgrNo2 = 32539
    - 여성 데님팬츠: dpCtgrNo2 = 32568
    - 여성 일반 팬츠/슬랙스: dpCtgrNo2 = 32529
    - 여성 자켓/아우터: dpCtgrNo2 = 32540

    - 남성 티셔츠: dpCtgrNo2 = 32618
    - 남성 팬츠/슬랙스: dpCtgrNo2 = 32609
    - 남성 셔츠: dpCtgrNo2 = 32619
    - 남성 니트/스웨터: dpCtgrNo2 = 32608
    - 남성 자켓/아우터: dpCtgrNo2 = 32540

    - 골프 여성 긴바지: dpCtgrNo3 = 111001004
    - 골프 남성 긴바지: dpCtgrNo3 = 111002001
    - 골프 여성 스커트: dpCtgrNo3 = 111001006
    - 골프 여성 반팔티: dpCtgrNo3 = 111001002
    - 골프 남성 반팔티: dpCtgrNo3 = 111002004
    """

    prompt = f"""
    당신은 전문 패션 스타일리스트입니다.
    제시된 기준 상품 정보를 분석하여 이에 가장 잘 어울리는 추천 코디 상품 3가지를 제안해주세요.
    
    [핵심 준수 사항]
    - 검색 필터(성별, 브랜드, 카테고리)에 해당하는 정보는 검색 키워드 쿼리에서 반드시 분리해야 합니다.
    - 추천 상품의 성별에 맞춰 'gnd_cd' 필터를 올바르게 설정해주세요.
    - 'brand_cd' 필터는 반드시 항상 빈 값("")으로 비워두세요. 추천 코디 상품의 브랜드는 기준 상품의 브랜드와 달라도 상관없습니다.
    - 추천하려는 코디 아이템을 아래의 카테고리 매핑 정보와 매칭하여 일치하는 경우 'category_level' 및 'category_code'를 작성해주세요.
    - 'search_keyword' 필드에는 카테고리, 브랜드, 성별 필터로 걸러지지 않는 스타일 특징 및 세부 속성(예: '린넨 와이드', '스카시', '스트라이프', '스트레치', '오버핏 린넨')만 작성해야 합니다. 'search_keyword'에 카테고리명(예: '바지', '티셔츠', '니트'), 성별 단어(예: '남성', '여성'), 브랜드명(예: '헤지스', '닥스')을 절대 포함하지 마세요.
    - 추천 이유인 'reason' 설명문은 반드시 친절한 어조의 한글로 작성해 주세요.
    
    카테고리 매핑 목록:
    {category_mapping_prompt}
    
    기준 상품 정보:
    {product_info}
    """
    
    contents = [prompt]
    if image:
        contents.append(image)
        
    try:
        response = call_gemini_with_retry(
            client=client,
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CoordiResponse,
                temperature=0.7,
            ),
        )
        return response.text
    except Exception as e:
        st.error(f"Gemini API 호출 오류: {e}")
        return None

def create_coordination_board(model_input, cloth_img_url):
    try:
        if isinstance(model_input, str):
            model_res = requests.get(model_input)
            model_res.raise_for_status()
            model_img = Image.open(BytesIO(model_res.content)).convert("RGBA")
        else:
            model_img = model_input.convert("RGBA")
            
        cloth_res = requests.get(cloth_img_url)
        cloth_res.raise_for_status()
        cloth_img = Image.open(BytesIO(cloth_res.content)).convert("RGBA")
    except Exception as e:
        st.error(f"코디 보드용 이미지를 가져오는데 실패했습니다: {e}")
        return None

    # Canvas Size: 1000 x 600
    canvas_w, canvas_h = 1000, 600
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (252, 250, 247, 255)) # Soft cream background
    draw = ImageDraw.Draw(canvas)
    
    target_h = 450
    target_w = 337 # 3:4 aspect ratio
    
    model_resized = ImageOps.fit(model_img, (target_w, target_h), Image.Resampling.LANCZOS)
    cloth_resized = ImageOps.fit(cloth_img, (target_w, target_h), Image.Resampling.LANCZOS)
    
    # Left: Reference Model Image (x=70, y=75)
    canvas.paste(model_resized, (70, 75), model_resized)
    # Right: Recommended Coordinating Item Image (x=593, y=75)
    canvas.paste(cloth_resized, (593, 75), cloth_resized)
    
    # Draw center divider / style card
    card_x1, card_y1 = 437, 75
    card_x2, card_y2 = 563, 525
    draw.rectangle([card_x1, card_y1, card_x2, card_y2], fill=(255, 255, 255, 255), outline=(210, 205, 200, 255), width=2)
    
    # Try to load Arial or fallback
    try:
        font_large = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 32)
        font_medium = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 16)
    except:
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        
    # Draw Matching Symbol and Styling text in the center card
    draw.text((500, 250), "+", fill=(139, 125, 112, 255), font=font_large, anchor="mm")
    draw.text((500, 310), "MATCHING", fill=(139, 125, 112, 255), font=font_medium, anchor="mm")
    
    # Labels
    draw.text((70 + target_w/2, 550), "Original Style", fill=(80, 80, 80, 255), font=font_medium, anchor="mm")
    draw.text((593 + target_w/2, 550), "Recommended Item", fill=(80, 80, 80, 255), font=font_medium, anchor="mm")
    
    return canvas.convert("RGB")

def generate_try_on_image(model_input, cloth_img_url, category_name="의류", add_img_urls=[]):
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    
    # 1. Fetch images
    try:
        if isinstance(model_input, str):
            model_res = requests.get(model_input)
            model_res.raise_for_status()
            model_img = Image.open(BytesIO(model_res.content))
        else:
            model_img = model_input
            
        cloth_res = requests.get(cloth_img_url)
        cloth_res.raise_for_status()
        cloth_img = Image.open(BytesIO(cloth_res.content))
    except Exception as e:
        st.error(f"이미지를 불러오는 데 실패했습니다: {e}")
        return None
        
    # Load additional product images if provided
    loaded_add_imgs = []
    for url in add_img_urls:
        try:
            res = requests.get(url)
            res.raise_for_status()
            loaded_add_imgs.append(Image.open(BytesIO(res.content)))
        except Exception:
            # Skip if any specific additional image fails to fetch
            pass
        
    # 2. Call gemini-3.1-flash-image to generate the try-on
    # We write a highly strict VTON instruction specifying what category to replace and keeping other elements identical.
    vton_prompt = f"""
    당신은 전문 패션 이미지 에디터입니다. 당신의 목표는 인물의 왜곡(환각 현상)을 방지하기 위해 다른 모든 요소는 정확히 동일하게 유지하면서, 오직 추천받은 코디 의류/신발 아이템만 모델에게 교체/착장하는 것입니다.
    
    - 이미지 1 (첫 번째 이미지): 기준이 되는 피팅 모델 이미지입니다. 주의: 이 모델은 이전 착장 단계를 거치며 이미 다른 새로운 코디 아이템(예: 새로운 바지, 아우터, 신발 등)을 착용하고 있는 상태일 수 있습니다. 이전 단계에서 추가된 착장 아이템을 절대 제거하거나 원래 옷으로 되돌리지 말고 그대로 보존(Preserve)해야 합니다.
    - 이미지 2 (두 번째 이미지): 모델에게 새로 추가하거나 교체하여 입혀야 할 코디 추천 상품입니다 (카테고리명: {category_name}).
    - 후속 이미지들 (제공된 경우): 추천 코디 상품의 추가 상세 컷, 누끼 컷, 원단 클로즈업 또는 상세 무늬 패턴 이미지들입니다.
    
    [준수 지침]
    1. 이미지 1의 모델 몸 위에서 오직 '{category_name}' 카테고리에 해당하는 의류/신발만 이미지 2의 아이템으로 교체/추가하세요.
    2. 모델이 입고 있는 다른 모든 의류(이미지 1에 존재하는 이전 착장 바지, 상의 셔츠, 또는 아우터 등)는 색상, 패턴, 스타일, 원단 질감, 단추, 소매 길이, 핏 등이 절대 변경되거나 원래 옷으로 되돌아가서는 안 되며, 100% 동일하게 유지되어야 합니다.
    3. 만약 3번째 이후의 상세/추가 이미지들이 제공되었다면, 해당 이미지들을 참고하여 추천 상품의 상세한 실루엣, 색감, 패턴, 고유 프린팅 무늬 및 원단 질감을 정확하게 인지하고 이를 모델의 몸 위에 높은 재현율(Fidelity)로 합성하세요.
    4. 만약 카테고리가 '신발'류이거나 이미지 1에서 인물의 발/다리 하단이 잘려서 보이지 않는 구도라면, 이미지 1 하단을 자연스럽게 확장(아웃페인팅)하여 다리와 발을 새로 생성해 내야 합니다. 새로 생성된 다리와 발 위에 이미지 2의 신발을 자연스럽게 신겨주세요. 새로 그려지는 발과 다리는 모델 원래의 신체 비율, 피부 톤, 자세에 맞아야 하며 바닷가/야외 배경도 아래쪽으로 어색함 없이 자연스럽게 연장되어야 합니다.
    5. 모델의 고유 신원(얼굴 생김새, 눈코입 형태), 헤어스타일, 피부색, 서 있는 포즈, 손목시계/장신구 및 상단 배경은 이미지 1과 100% 완벽히 동일하게 유지하세요.
    6. 모델이 추천 의류 및 신발을 자연스럽게 착용한 최종 고화질의 패션 카탈로그 사진 결과물만을 이미지로 반환하세요.
    """
    
    # Bundle prompt, model image, primary clothing image, and additional detailed product images
    gemini_contents = [
        vton_prompt,
        model_img,
        cloth_img
    ] + loaded_add_imgs
    
    try:
        response = call_gemini_with_retry(
            client=client,
            model='gemini-3.1-flash-image',
            contents=gemini_contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio="3:4",
                ),
            ),
        )
        
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                return Image.open(BytesIO(part.inline_data.data))
                
        st.error("생성된 이미지가 없습니다.")
        return None
    except Exception as e:
        st.warning(f"Gemini 가상 착장 모델 호출 중 오류가 발생하여 코디 보드로 대체합니다: {e}")
        # Fallback: Lookbook Coordination Board (0% Hallucination)
        return create_coordination_board(model_input, cloth_img_url)
