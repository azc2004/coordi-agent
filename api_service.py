import requests

def fetch_product_list():
    url = "https://hapix.halfclub.com/searches/prdList/?selAcntCd=A6082&limit=0,40&sortSeq=12&siteCd=1&device=pc&icnSet="
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get("data", {}).get("result", {}).get("hits", {}).get("hits", [])
    except Exception as e:
        print(f"Error fetching product list: {e}")
        return []

def fetch_product_info(prd_no):
    url = f"https://hapix.halfclub.com/product/products/withoutPrice/{prd_no}?countryCd=001&langCd=001&siteCd=1&deviceCd=001"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching product info for {prd_no}: {e}")
        return None

def search_products(keyword, gnd_cd=None, brand_cd=None, cat_level=None, cat_code=None):
    url = f"https://hapix.halfclub.com/searches/prdList/?keyword={keyword}&device=pc&limit=0,20&sortSeq=12"
    if gnd_cd:
        url += f"&gndCd={gnd_cd}"
    if brand_cd:
        url += f"&brandCd={brand_cd}"
    if cat_level and cat_code:
        url += f"&{cat_level}={cat_code}"
        
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get("data", {}).get("result", {}).get("hits", {}).get("hits", [])
    except Exception as e:
        print(f"Error searching products: {e}")
        return []
