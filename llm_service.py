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
                temperature=0.7,
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
    styling_rules.append(f"{rule_idx}. [매우 중요] 하의(팬츠, 청바지, 슬랙스 등)는 절대 반으로 접거나 구기지 말고, 다리 모양 그대로 아래로 길게 일자로 완전히 펼쳐진 상태(Laid out straight without folding)로 배치하세요. 그리고 신발(구두, 부츠, 샌들 등)은 일자로 펼쳐진 하의의 맨 밑단 바로 아래에 자연스럽게 맞닿아 이어지도록 배치하여 실제 서 있는 다리 실루엣처럼 연출하세요.")
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
    인물 모델 없이 의류/소품들만 바닥에 눕혀 코디하는 감각적인 '플랫레이(Flat-lay)' 사진을 만들어야 합니다.

    [상황/날씨 연출 분위기]
    {weather_desc}
    위 날씨/상황의 분위기가 느껴지는 감성적이고 부드러운 스튜디오 바닥 배경(예: 밝은 우드, 대리석, 패브릭 매트 등)을 사용하세요.
    {prd_context}
    [핵심 준수 지침]
    1. 각 상품의 위치는 '인체(몸)의 실제 착용 위치'에 맞게 직관적으로 정렬해주세요. (예: 상의는 화면의 위쪽 중앙, 하의는 상의의 바로 아래쪽, 신발은 하의 맨 아래쪽, 가방이나 소품은 자연스럽게 측면에 배치).{styling_rules_text}
    {rule_idx}. 제공된 코디 구성 상품 사진에 있는 제품들은 반드시 결과물 사진에 명확하고 비중 있게 노출되어야 합니다. 누락되는 상품이 없어야 합니다.
    {rule_idx+1}. 제공된 상품 이미지들의 형태, 색상, 로고, 패턴, 디테일을 환각(Hallucination)이나 변형 없이 100% 동일하게 유지하여 극도로 사실적으로 표현하세요. 제공된 실물 상품이 사진의 주인공입니다.
    {rule_idx+2}. [매우 중요] 이미지 위에 제품과 무관한 어떠한 글자/텍스트(예: SIZE, 2color, COOL 등), 아이콘(온도계, 화살표 등), 로고, 그래픽 요소도 절대 생성하지 마세요. 오직 옷과 자연스러운 바닥 배경만 존재해야 합니다.
    {rule_idx+3}. [경고] 입력 이미지로 제공되지 않은 다른 의류, 신발, 가방, 액세서리 등을 임의로 추가하여 그리지 마세요. 오직 입력 이미지로 제공된 상품들만 사용하여 코디 샷을 완성해야 하며, 제품의 총 개수는 제공된 입력 이미지의 개수({len(component_images)}개)와 정확히 일치해야 합니다.
    {rule_idx+4}. 이미지는 세로형(3:4 비율) 포스터 컷으로 렌더링하세요.
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

