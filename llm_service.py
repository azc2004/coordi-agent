import streamlit as st
import json
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
    필터링 가능한 카테고리 정보 (category_level 및 category_code):
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

class OutfitComponent(BaseModel):
    category: str = Field(description="코디 품목 구분 (예: 상의, 하의, 신발, 가방, 아우터 등)")
    gnd_cd: str = Field(description="성별 코드 ('01': 남성, '02': 여성, '03': 남녀공용)")
    category_level: str = Field(description="카테고리 필터 레벨 ('dpCtgrNo2' 또는 'dpCtgrNo3' 또는 '')")
    category_code: str = Field(description="카테고리 번호 (제공된 매핑 목록에 일치할 시, 없으면 '')")
    search_keyword: str = Field(description="하프클럽 상품 검색을 위한 검색어. 성별, 브랜드, 카테고리명을 제외한 스타일 속성 키워드 (예: '러플 린넨 블라우스', '핀턱 와이드 슬랙스', '가죽 스트랩 샌들')")

class ContextAwareOutfitResponse(BaseModel):
    theme: str = Field(description="오늘의 코디 스타일링 테마 제목 (예: '러블리 비즈니스 캐주얼룩', '화사한 써머 데이트룩')")
    description: str = Field(description="이 코디에 대한 스타일링 가이드 및 설명. 퀀잇 사이트 어조처럼 상세하고 친근한 존댓말 한글로 작성 (2~3문장).")
    tags: list[str] = Field(description="코디에 어울리는 감성적인 해시태그 목록 (예: ['#부슬부슬', '#러플블라우스', '#데이트룩'])")
    components: list[OutfitComponent] = Field(description="이 코디를 구성하는 3~4개의 패션 아이템 상세 사양 목록")

def generate_context_aware_outfit(target_date: str, weather: str, gender: str, age_group: str, situation: str, personal_color: str, style_preference: str):
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    
    category_mapping_prompt = """
    필터링 가능한 카테고리 정보 (category_level 및 category_code):
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
    """

    prompt = f"""
    당신은 퀀잇(Queenit) 스타일의 전문 패션 디렉터입니다.
    오늘의 상황 정보를 바탕으로 가장 멋진 '오늘의 코디'를 제안해주세요.

    [상황 정보]
    - 날짜: {target_date}
    - 날씨: {weather}
    - 상황(TPO): {situation}
    - 타겟 성별: {gender}
    - 타겟 연령대: {age_group}
    - 퍼스널 컬러: {personal_color}
    - 선호 스타일: {style_preference}

    [준수 지침]
    - 이 상황(날짜, 날씨, TPO)과 타겟(성별, 연령대, 퍼스널 컬러, 선호 스타일)에 완벽하게 어울리는 코디 테마 제목(theme), 설명(description), 감성 태그(tags), 그리고 구성 품목(components, 3~4개)을 작성합니다.
    - 상황(TPO)에 맞추어 엄격한 스타일링 규칙을 적용하세요 (예: 장례식/조문인 경우 무조건 어두운 무채색 계열과 단정한 핏, 결혼식 하객인 경우 신부의 색인 흰색을 피하고 포멀한 핏 등).
    - 퍼스널 컬러나 선호 스타일이 '선택 안함'이 아닐 경우, 해당 컬러 팔레트와 스타일 무드를 코디에 적극 반영하세요.
    - 설명(description)은 퀀잇 '오늘의 코디'처럼 상세하고 친근한 존댓말로, 오늘 입으면 왜 좋은지 설명해주세요.
    - 구성 품목(components)은 상의, 하의, 신발, (선택적: 아우터 또는 가방/우산 등)으로 구성해주세요.
    - 카테고리 매핑 정보에 일치하는 품목이 있다면 category_level과 category_code를 정확히 지정하고, 없으면 빈 문자열("")로 두세요.
    - search_keyword에는 카테고리명(예: 바지, 셔츠, 신발)이나 성별을 제외하고 스타일 특징(예: '비비드 린넨', '하이웨이스트 핀턱', '레인부츠')만 담아주세요.
    - 성별(gnd_cd) 코드는 남성이면 '01', 여성이면 '02', 공용이면 '03'으로 올바르게 지정하세요.

    카테고리 매핑 목록:
    {category_mapping_prompt}
    """
    
    try:
        response = call_gemini_with_retry(
            client=client,
            model='gemini-2.5-flash',
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ContextAwareOutfitResponse,
                temperature=1.0,
            ),
        )
        return response.text
    except Exception as e:
        st.error(f"Gemini API 호출 오류: {e}")
        return None

def create_flatlay_fallback_board(component_images):
    # Pillow로 잡지 화보 느낌의 캔버스 생성
    # component_images: list of PIL.Image
    n = len(component_images)
    if n == 0:
        return None
        
    canvas_w, canvas_h = 900, 1200 # 3:4 비율 (가로 900, 세로 1200)
    canvas = Image.new("RGB", (canvas_w, canvas_h), (247, 245, 242)) # 크림색 배경
    
    if n == 1:
        img = ImageOps.fit(component_images[0], (800, 1100), Image.Resampling.LANCZOS)
        canvas.paste(img, (50, 50))
    elif n == 2:
        img1 = ImageOps.fit(component_images[0], (800, 500), Image.Resampling.LANCZOS)
        img2 = ImageOps.fit(component_images[1], (800, 500), Image.Resampling.LANCZOS)
        canvas.paste(img1, (50, 50))
        canvas.paste(img2, (50, 650))
    elif n == 3:
        img1 = ImageOps.fit(component_images[0], (800, 600), Image.Resampling.LANCZOS) # 메인(상의 등)
        img2 = ImageOps.fit(component_images[1], (380, 450), Image.Resampling.LANCZOS) # 하의
        img3 = ImageOps.fit(component_images[2], (380, 450), Image.Resampling.LANCZOS) # 신발/가방
        canvas.paste(img1, (50, 50))
        canvas.paste(img2, (50, 700))
        canvas.paste(img3, (470, 700))
    else:
        # 4개 이상
        img1 = ImageOps.fit(component_images[0], (380, 500), Image.Resampling.LANCZOS)
        img2 = ImageOps.fit(component_images[1], (380, 500), Image.Resampling.LANCZOS)
        img3 = ImageOps.fit(component_images[2], (380, 500), Image.Resampling.LANCZOS)
        img4 = ImageOps.fit(component_images[3], (380, 500), Image.Resampling.LANCZOS)
        canvas.paste(img1, (50, 50))
        canvas.paste(img2, (470, 50))
        canvas.paste(img3, (50, 650))
        canvas.paste(img4, (470, 650))
        
    return canvas

def generate_outfit_flatlay_image(component_images, weather_desc, product_names=None, has_bag=False, has_outer=False):
    if not component_images:
        return None
        
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    
    # Conditionally generate layout guidelines to prevent hallucination
    styling_rules = []
    rule_idx = 2
    
    # Strict rule for straight pants and shoes alignment
    styling_rules.append(f"{rule_idx}. [매우 중요] 하의(팬츠, 청바지, 슬랙스 등)는 절대 반으로 접거나 구기지 말고, 다리 모양 그대로 아래로 길게 일자로 완전히 펼쳐진 상태(Laid out straight without folding)로 배치하세요. 그리고 신발(구두, 부츠, 스니커즈 등)은 일자로 펼쳐진 하의의 맨 밑단 바로 아래에 자연스럽게 맞닿아 이어지도록 배치하여 실제 서 있는 다리 실루엣처럼 연출하세요.")
    rule_idx += 1
    
    if has_outer:
        styling_rules.append(f"{rule_idx}. [매우 중요] 코디 상품에 '외투/아우터(코트, 자켓, 가디건 등)'가 포함되어 있으므로, 외투를 상의 밑에 깔아두지 마세요. 외투가 상의(블라우스, 셔츠 등) 바깥쪽을 덮거나 걸쳐진 형태로 그리세요 (즉, 상의는 안쪽에 입고 외투가 겉에 입혀진 상태여야 함).")
        rule_idx += 1
        
    if has_bag:
        styling_rules.append(f"{rule_idx}. [매우 중요] 코디 상품에 '가방'이 포함되어 있으므로, 가방을 구석 바닥에 따로 두지 마세요. 가방의 어깨끈(Strap)이 상의/아우터의 어깨 부위에 자연스럽게 걸쳐져 흘러내리는 '어깨에 메고 있는 형태'로 겹쳐서 입체적으로 배치하세요.")
        rule_idx += 1
        
    styling_rules_text = "\n    ".join(styling_rules)
    if styling_rules_text:
        styling_rules_text = "\n    " + styling_rules_text
        
    prd_context = ""
    if product_names:
        prd_list_str = ", ".join([f"'{p}'" for p in product_names])
        prd_context = f"\n    [제공된 실제 코디 상품 목록]\n    - {prd_list_str}\n"
    
    prompt = f"""
    당신은 최상급 패션 매거진의 디렉터이자 포토그래퍼입니다. 
    제공된 {len(component_images)}개의 실제 패션 상품 이미지들을 사용하여, 
    인물 모델 없이 의류/소품들만 바닥에 눕혀 코디하는 극도로 자연스럽고 감각적인 '플랫레이(Flat-lay)' 사진을 만들어야 합니다.

    [상황/날씨 연출 분위기]
    {weather_desc}
    위 날씨/상황의 분위기가 느껴지는 감성적이고 부드러운 스튜디오 바닥 배경(예: 밝은 우드, 대리석, 패브릭 매트 등)을 사용하세요.
    {prd_context}
    [핵심 준수 지침]
    1. 각 상품의 위치는 '인체(몸)의 실제 착용 위치'에 맞게 직관적이고 자연스러운 겹침(Layered layout)으로 배치해주세요.
       - **상의 레이어드 겹침 규칙**: 만약 셔츠, 티셔츠, 카디건 등 여러 장의 상의가 제공되었을 경우, 제품을 낱개로 분리해 놓지 마세요. 이너웨어(예: 흰색 티셔츠) 위에 아우터 셔츠(예: 파란색 셔츠)나 자켓이 겹쳐져 입혀진 일체형 레이어드 룩(Layered style)으로 렌더링하세요. 이너의 넥라인이 아우터 셔츠/자켓의 깃(카라) 틈새로 부드럽게 노출되는 한 벌의 자연스러운 레이어드 상태여야 합니다.
       - **하의와 상의의 연결**: 하의(바지/청바지/슬랙스)는 상의 밑단과 자연스럽게 맞닿아 이어지도록 배치하세요. (필요 시 상의 밑단을 하의 허리춤 안으로 집어넣은 'Tuck-in' 스타일로 연출해 실제 착장 비율과 일치시키세요).
       - **모자(HAT)의 위치**: 모자(볼캡 등)가 구성품에 있을 경우, 상의 넥라인의 바로 위쪽(머리 위치)에 자연스러운 각도로 비스듬히 놓아 정수리 실루엣을 완성하세요.
       - **벨트(BELT)의 위치**: 벨트가 구성품에 있을 경우, 하의 바지의 허리 벨트라인 구멍에 꿰어진 형태로 착용 샷처럼 정교하게 합성하여 배치하세요.
       - 신발은 하의 맨 밑단 아래에, 가방은 자연스럽게 측면 혹은 상의 어깨끈에 걸치도록 배치하세요.{styling_rules_text}
    {rule_idx}. 제공된 코디 구성 상품 사진에 있는 제품들은 반드시 결과물 사진에 명확하고 비중 있게 노출되어야 합니다. 누락되는 상품이 없어야 합니다.
    {rule_idx+1}. 제공된 상품 이미지들의 형태, 색상, 로고, 패턴, 디테일을 환각(Hallucination)이나 변형 없이 100% 동일하게 유지하여 극도로 사실적으로 표현하세요. 제공된 실물 상품이 사진의 주인공입니다.
    {rule_idx+2}. [매우 중요] 이미지 위에 제품과 무관한 어떠한 글자/텍스트(예: SIZE, 2color, COOL 등), 아이콘(온도계, 화살표 등), 로고, 그래픽 요소도 절대 생성하지 마세요. 오직 옷과 자연스러운 바닥 배경만 존재해야 합니다.
    {rule_idx+3}. [경고] 입력 이미지로 제공되지 않은 다른 의류, 신발, 가방, 액세서리 등을 임의로 추가하여 그리지 마세요. 오직 입력 이미지로 제공된 상품들만 사용하여 코디 샷을 완성해야 하며, 제품의 총 개수는 제공된 입력 이미지의 개수({len(component_images)}개)와 정확히 일치해야 합니다.
    {rule_idx+4}. 이미지는 세로형(3:4 비율) 포스터 컷으로 렌더링하세요.

    [★초특급 경고 - 신발(구두, 스니커즈, 로퍼 등)의 상하 정방향 배치 규칙]
    - 신발을 배치할 때, 신발의 뒤꿈치 및 발목이 들어가는 입구(Open heel/opening)가 무조건 '위쪽(하의 바지 밑단 방향)'을 향하게 하세요.
    - 신발의 둥근 앞코(Toes)는 무조건 '아래쪽(화면의 맨 밑바닥 방향)'을 가리키도록 하세요.
    - 입력 이미지(누끼 사진)에서 신발의 앞코가 위를 가리키고 있더라도, 화보에서는 **반드시 180도 회전시켜 앞코가 아래를 향하게 그리십시오.**
    - 신발의 앞코가 위쪽을 가리키며 바지 밑단을 파고들어가는 거꾸로 뒤집힌(upside-down) 형태는 사람이 물구나무를 선 실루엣이 되므로 절대 생성 금지합니다.
    """
    
    contents = [prompt] + component_images
    
    try:
        response = call_gemini_with_retry(
            client=client,
            model='gemini-3.1-flash-image',
            contents=contents,
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
                
        # 실패 시 Fallback
        return create_flatlay_fallback_board(component_images)
    except Exception as e:
        st.warning(f"AI 코디 화보 생성 실패, 캔버스 보드로 대체합니다: {e}")
        return create_flatlay_fallback_board(component_images)

class ItemLocation(BaseModel):
    item_index: int
    item_name: str
    location_description: str
    x: int
    y: int

class ItemLocationsResponse(BaseModel):
    locations: list[ItemLocation]

def detect_item_coordinates(image, numbered_keywords):
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    
    # Clean the keywords to match what's shown
    keywords_clean = [k.split("_")[-1] if "_" in k else k for k in numbered_keywords]
    
    prompt = f"""
    당신은 패션 이미지 분석가입니다.
    제공된 패션 플랫레이(Flat-lay) 이미지에서 다음 아이템들의 정중앙 중심점 좌표(x, y)를 정밀하게 검출해야 합니다.
    각 아이템의 실제 옷/모자/가방/신발 등이 캔버스 상에서 그려져 있는 영역의 한가운데를 가리키는 x, y 백분율 좌표(0~100)를 구하세요.
    
    분석할 아이템 목록:
    {", ".join([f"인덱스 {idx}: {k}" for idx, k in enumerate(keywords_clean)])}
    
    각 아이템에 대해 다음 정보를 응답 스키마에 맞춰 작성하세요:
    1. item_index: 해당 아이템의 인덱스 번호
    2. item_name: 아이템의 한글 명칭
    3. location_description: 이미지 내에서 해당 상품의 색상, 형태적 특징 및 정확한 위치 설명 (예: '베이지색 모자는 좌측 상단 영역에 단독으로 놓여 있음', '흰색 반팔 티셔츠는 중앙 상단에 위치함')
    4. x: 상품 정중앙의 가로 백분율 좌표 (0 = 왼쪽 가장자리, 100 = 오른쪽 가장자리)
    5. y: 상품 정중앙의 세로 백분율 좌표 (0 = 위쪽 가장자리, 100 = 아래쪽 가장자리)
    
    의류/소품 분류별 대략적 위치 및 좌표 참고:
    - 모자(버킷햇, 볼캡 등): 보통 좌측/우측 상단 구석 혹은 상의 위쪽 머리 부위 (y=5~25 범위)
    - 상의(블라우스, 셔츠, 티셔츠): 보통 y=20~45 범위의 중앙부
    - 하의(스커트, 팬츠, 슬랙스): 보통 y=45~80 범위의 중앙부
    - 신발(부츠, 샌들, 펌프스): 보통 y=75~95 범위의 최하단 중앙부
    - 아우터(가디건, 코트, 자켓) 및 가방(토트백, 숄더백): 해당 제품이 실제로 렌더링되어 놓여있는 구역
    """
    
    try:
        buffered = BytesIO()
        img_rgb = image.convert("RGB") if image.mode in ("RGBA", "P") else image
        img_rgb.save(buffered, format="JPEG")
        img_bytes = buffered.getvalue()
        
        image_part = types.Part.from_bytes(
            data=img_bytes,
            mime_type="image/jpeg",
        )
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt, image_part],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ItemLocationsResponse,
            ),
        )
        data = json.loads(response.text)
        locations = data.get("locations", [])
        
        # Build mapping from numbered_keywords to coordinates
        coord_map = {}
        for num_kw in numbered_keywords:
            coord_map[num_kw] = None
            
        for loc in locations:
            idx = loc.get("item_index")
            if idx is not None and 0 <= idx < len(numbered_keywords):
                num_kw = numbered_keywords[idx]
                coord_map[num_kw] = {
                    "x": int(loc.get("x", 50)),
                    "y": int(loc.get("y", 50))
                }
        return coord_map
    except Exception as e:
        print(f"Error detecting item coordinates: {e}")
        return {}

class TrendEvaluationResponse(BaseModel):
    trend_score: int
    color_score: int
    fit_score: int
    trend_analysis: str

def evaluate_outfit_trendiness(theme, description, tags, products_list):
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    
    products_desc = "\n".join([
        f"- Brand: {p.get('brandNm', '')}, Name: {p.get('prdNm', '')}"
        for p in products_list
    ])
    
    prompt = f"""
    당신은 대한민국 최고의 트렌디한 패션 매거진 수석 에디터이자 스타일 검증관입니다.
    제안된 다음 코디 조합이 실제로 대한민국 최신(2025~2026년) 패션 트렌드 선호도에 부합하는지 정밀 검증하고 채점해야 합니다.
    
    [제안된 코디 정보]
    - 테마: {theme}
    - 스타일 설명: {description}
    - 스타일 태그: {", ".join(tags)}
    
    [구성 상품 목록]
    {products_desc}
    
    다음 4가지 항목에 대해 응답 스키마에 맞춰 정보를 생성하세요:
    1. trend_score (트렌드 적합도): 2025~2026년 2030 세대 사이에서 유행하는 핵심 스타일링 키워드(예: Quiet Luxury/올드머니, Gorpcore/고프코어, Minimalism/미니멀리즘, Blockcore/블록코어, Y2K 레트로, Office Siren 등)와 실질적 매칭도 (1~10점 정수)
    2. color_score (컬러 조화도): 상/하의, 아우터, 신발 간의 톤온톤, 톤인톤, 혹은 대비 배색이 세련되고 트렌디하게 이루어졌는지 여부 (1~10점 정수)
    3. fit_score (실루엣 및 핏 밸런스): 상의의 핏(오버핏, 세미오버핏 등)과 하의(와이드, 스트레이트, 카고 등) 및 신발의 부피감이 조화롭게 조율되었는지 여부 (1~10점 정수)
    4. trend_analysis (트렌드 분석 리포트): 위 채점 결과를 뒷받침하는 트렌드 부합 원인 분석을 친근하면서도 전문적인 한국어 문장(존댓말)으로 상세히 설명하십시오.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TrendEvaluationResponse,
                temperature=0.7,
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error evaluating trendiness: {e}")
        return {
            "trend_score": 8,
            "color_score": 8,
            "fit_score": 8,
            "trend_analysis": "이 코디는 조화로운 실루엣과 감각적인 색상 배합을 통해 현재 트렌디한 일상 캐주얼 룩의 정수를 잘 보여줍니다."
        }


def generate_full_outfit_try_on(model_img, flatlay_img, theme="코디 스타일", gender="여성", age="30대"):
    """
    코디 완성 플랫레이(Flat-lay) 이미지에 있는 모든 의상을
    성별과 연령대에 매치되는 가상 고정 모델 위에 자연스럽게 일괄 착장(VTON)하여 전신 패션 화보 컷을 생성합니다.
    """
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    
    prompt = f"""
    당신은 전문 패션 이미지 에디터입니다.
    제공된 이미지들을 활용하여, 모델이 '코디 완성 사진(바닥에 눕혀 코디된 플랫레이 화보)'에 있는 모든 의류와 소품들을 자연스럽게 착용한 최종 전신 화보 컷을 생성하는 것이 당신의 임무입니다.
    
    - 이미지 1 (첫 번째 이미지): 가상의 기본 피팅 모델 이미지입니다 (성별: {gender}, 연령대: {age}). 이 모델의 고유한 얼굴 생김새, 체형 비율, 헤어스타일, 그리고 포즈의 느낌을 그대로 보존해야 합니다.
    - 이미지 2 (두 번째 이미지): 여러 의류, 바지, 신발, 가방 등이 조화롭게 코디된 '코디 완성 사진(Flat-lay)' 화보입니다.
    
    [준수 지침]
    1. 이미지 2(코디 완성 사진)에 포함된 상의, 하의, 아우터(있는 경우), 신발, 가방(있는 경우) 등의 모든 패션 아이템들을 이미지 1의 피팅 모델 몸 위에 완벽하게 일체화시켜 자연스러운 '착장 샷'으로 표현하세요.
    2. 코디 완성 사진에 배치된 각 제품의 고유한 색상, 패턴, 소재의 질감, 단추 및 실루엣을 100% 반영하여 피팅 모델에게 정확하게 입혀주세요.
    3. 모델의 원래 피부 톤, 머리 모양, 고유 신원은 이미지 1과 매우 흡사하고 자연스럽게 유지되어야 합니다.
    4. 모델은 이미지 2의 감각적인 스타일과 테마('{theme}')에 걸맞는 자연스럽고 자신감 있는 전신 포즈로 고품질의 패션 매거진 카탈로그 화보처럼 연출되어야 합니다.
    5. 이미지 위에 어떠한 텍스트나 로고, 불필요한 그래픽 요소도 생성하지 마세요.
    """
    
    try:
        response = call_gemini_with_retry(
            client=client,
            model='gemini-3.1-flash-image',
            contents=[prompt, model_img, flatlay_img],
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
                
        return None
    except Exception as e:
        st.error(f"AI 가상 코디 착장 생성 중 오류가 발생했습니다: {e}")
        return None


class ImageItemAnalysis(BaseModel):
    category: str = Field(description="추천하는 코디 상품의 품목 카테고리 (예: 바지, 스커트, 원피스, 셔츠, 티셔츠, 아우터 등)")
    gnd_cd: str = Field(description="추천 상품의 성별 필터 코드. 남성은 '01', 여성은 '02', 남녀공용은 '03' 필수 입력.")
    category_level: str = Field(description="카테고리 필터 레벨. 카테고리 매핑 정보와 일치할 시 'dpCtgrNo2' 또는 'dpCtgrNo3'를 입력하며, 일치하지 않으면 빈 문자열(\"\")을 입력합니다.")
    category_code: str = Field(description="제공된 카테고리 매핑 목록 중 해당하는 카테고리 번호. 해당하는 정보가 없으면 빈 문자열(\"\")로 채웁니다.")
    search_keyword: str = Field(description="자사 검색 API에 전달할 정교하고 함축적인 패션 속성 검색 쿼리 키워드. 품목 카테고리 명칭(예: '바지', '스커트', '원피스' 등), 브랜드명, 성별 단어는 절대 빼고, 스타일링 특징(예: '스트라이프 카라', '린넨 와이드', '체크 플리츠')만 입력하세요.")
    description: str = Field(description="사진 속 모델의 해당 아이템 스타일에 대한 간단한 묘사.")

class ImageCoordiResponse(BaseModel):
    gender: str = Field(description="사진 속 인물의 성별 ('여성' 또는 '남성')")
    age: str = Field(description="사진 속 인물의 예상 연령대 ('20대', '30대', '40대', '50대', '60대', '70대 이상')")
    items: list[ImageItemAnalysis]

def analyze_image_and_extract_coordi(image):
    """
    사용자가 업로드한 착장 이미지(Vision)를 파싱하여, 모델이 입고 있는 패션 아이템들을
    자사 검색 API용 상세 카테고리 필터 및 키워드로 변환하여 추출합니다.
    """
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    
    category_mapping_prompt = """
    필터링 가능한 카테고리 정보 (category_level 및 category_code):
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
    당신은 일류 패션 이미지 분석가이자 스타일리스트입니다.
    제시된 이미지(사진 속 모델)의 착장을 세밀히 분석하여, 모델이 입고 있는 모든 패션 아이템(상의, 하의, 아우터, 신발, 가방 등 전신 구성 요소 및 모자, 벨트 등 잡화)을 자사 상품 검색 API를 통해 찾을 수 있도록 정확하게 구조화해서 상세 속성을 추출해 주세요.
    
    [핵심 추출 및 매핑 지침]
    1. 사진 속 모델의 전체적인 연령대와 성별을 식별해주세요. (예: 여성, 30대)
    2. 모델이 **실제로 '몸에 착용하고 있는(입거나 메고 있거나 신고 있거나 머리에 썼거나 허리에 찬)' 실질적인 의류 및 잡화(상의, 하의/스커트/원피스, 아우터, 신발, 가방, 모자, 벨트 등)**를 아이템 요소로 누락 없이 정교하게 추출합니다. (최대 5~6개 품목)
       - **[주의]** 모델이 머리에 쓴 모자(볼캡, 비니, 버킷햇 등)와 허리에 착용한 벨트(가죽 벨트 등)는 코디 완성도에 핵심적이므로 **반드시** 별도 아이템으로 추출하세요.
       - 모델이 손에 대충 뭉쳐서 쥐고 있거나 들고 있는 자켓/코트 등 '착용하지 않은 의류'는 아우터로 절대 추출하지 말고 완전히 무시(Ignore)하세요. 오직 몸에 걸치고 있는 의류만 아우터로 간주합니다.
       - 쇼핑백, 스마트폰, 액세서리(선글라스, 팔찌) 등은 가방이나 상품으로 추출하지 마세요.
    3. 각 아이템을 아래의 '카테고리 매핑 목록' 정보와 대조하여 매치되는 항목이 있다면 'category_level' 및 'category_code'를 명확히 작성해주고, 성별 'gnd_cd' 코드를 성별에 맞춰 채워주세요. (여성이면 '02', 남성이면 '01'). 모자나 벨트는 카테고리 매핑에 없으므로 category_level과 category_code는 빈 문자열("")로 지정합니다.
    4. 'search_keyword' 필드는 자사 API 검색 정확도를 위해 매우 중요합니다. 
       - 검색 키워드는 반드시 [색상/소재 + 디테일 특징 + 아이템 종류 명사]의 결합형태로 정교하게 작성해야 합니다.
       - 종류 명사는 자사 검색기가 인식할 수 있도록 반드시 포함되어야 합니다.
         (예: '블랙 폴로 반팔 티셔츠', '와이드 생지 데님 청바지', '브라운 가죽 숄더백', '옐로우 러닝 스니커즈', '베이지 린넨 셔츠', '그레이 숏 패딩 아우터', '화이트 네이비 볼캡 모자', '블랙 꼬임 가죽 벨트')
       - 단, 성별 단어(남성, 여성)나 브랜드명(폴로랄프로렌, 리바이스 등)은 검색에 불필요하므로 제외합니다.
    5. 사진 속 각 아이템에 대한 간결한 묘사를 'description'에 담아 주세요.
    
    카테고리 매핑 목록:
    {category_mapping_prompt}
    """
    
    try:
        response = call_gemini_with_retry(
            client=client,
            model='gemini-2.5-flash',
            contents=[prompt, image],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ImageCoordiResponse,
                temperature=0.4,
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error analyzing fashion image: {e}")
        return None


class VisualMatchResult(BaseModel):
    best_index: int = Field(description="후보 리스트 중 대상 아이템 비주얼과 가장 유사한 상품의 0-indexed 인덱스 번호. 만약 단 하나의 후보도 충분히 유사하지 않거나 스타일이 어울리지 않으면 -1을 입력해 주세요.")
    reason: str = Field(description="가장 유사하다고 판단한 비주얼적 근거 (색상, 실루엣, 소재 등 대조 분석).")

def select_best_visual_match(item_desc, candidate_images_and_details):
    """
    Gemini Vision을 사용하여, AI가 이미지에서 분석해낸 특정 아이템 묘사와
    자사 검색 API 결과 후보군들의 비주얼(썸네일 이미지)을 직접 1:1 대조하여
    가장 시각적 싱크로율이 높고 스타일이 유사한 상품을 골라냅니다.
    """
    client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    
    prompt = f"""
    당신은 일류 패션 비주얼 머천다이저입니다.
    대상 아이템 묘사 정보와 일치하고 시각적(색상, 형태, 소재감, 디테일)으로 가장 유사도가 높은 최적의 상품을 후보 목록에서 한 개 골라주세요.
    
    [대상 아이템 요구 속성]
    {item_desc}
    
    [준수 지침]
    1. 제공된 후보 상품 이미지 및 상품 정보를 보고, 대상 아이템의 색상, 디자인, 카테고리와 가장 완벽히 일치하는 상품의 인덱스 번호(0부터 시작)를 반환하세요.
    2. **[유사 대체재 허용 지침]**:
       - 만약 대상 아이템의 특정 색상(예: '옐로우/노란색')과 100% 동일한 색상의 후보 상품이 목록에 단 하나도 없을 경우, **대상의 '종류'(예: 스니커즈/운동화)를 최우선으로 지켜서 가장 스타일이 유사하고 무난한 대체 색상(예: 블랙, 화이트, 그레이 등의 무채색 또는 무난한 캐주얼 운동화)을 차선책으로 선택**해 주십시오. 
       - 즉, 노란색 운동화가 없다고 해서 아예 매칭을 드랍(-1)하기보다는, 캐주얼 룩의 완성도를 위해 **검정/흰색 캐주얼 스니커즈**를 차선책으로 선택하는 것이 좋습니다.
       - 그러나, 아예 종류가 전혀 다른 아이템(예: 운동화를 매칭해야 하는데 '쪼리 슬리퍼', '정장 가죽 구두' 등)은 절대로 선택하지 말고 완전히 배제(-1)해야 합니다.
    3. 색상이나 디자인이 전체 룩의 무드와 너무 엇나가서 코디 완성도를 망치는 부적격 상품(예: 격자무늬나 화려한 패턴이 들어간 중후한 패딩 자켓 등)은 과감하게 고르지 말고 -1을 반환하세요.
    """
    
    contents = [prompt]
    details_text = "\n[후보 상품 목록]\n"
    has_valid_images = False
    
    for idx, item in enumerate(candidate_images_and_details):
        details_text += f"- 후보 인덱스 {idx}: 상품명: {item.get('prdNm', '')}, 브랜드: {item.get('brandNm', '')}, 카테고리: {item.get('dpCtgrNm2', '')}\n"
        img = item.get('_pil_image')
        if img:
            contents.append(f"후보 인덱스 {idx} 이미지:")
            contents.append(img)
            has_valid_images = True
            
    contents.append(details_text)
    
    # If no candidate has images, return first one or -1
    if not has_valid_images:
        return 0 if candidate_images_and_details else -1
        
    try:
        response = call_gemini_with_retry(
            client=client,
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VisualMatchResult,
                temperature=0.2,
            ),
        )
        res_data = json.loads(response.text)
        return res_data.get("best_index", -1)
    except Exception as e:
        print(f"Error in select_best_visual_match: {e}")
        return -1


