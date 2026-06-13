"""菜系/餐饮偏好词汇表（中英文 + ChinaTravel 数据字段对齐）。"""

CUISINE_MAP_EN = {
    "local": "local",
    "local food": "local",
    "local cuisine": "local",
    "local specialty": "local",
    "local specialties": "local",
    "sichuan": "Sichuan cuisine",
    "sichuan cuisine": "Sichuan cuisine",
    "sichuan food": "Sichuan cuisine",
    "hotpot": "hotpot",
    "hot pot": "hotpot",
    "tea house": "Teahouse",
    "teahouse": "Teahouse",
    "cantonese": "Cantonese cuisine",
    "cantonese cuisine": "Cantonese cuisine",
    "dim sum": "Dim sum",
    "dimsum": "Dim sum",
    "beijing roast duck": "Beijing roast duck",
    "peking duck": "Beijing roast duck",
    "noodles": "Noodles",
    "dumplings": "Dumplings",
    "seafood": "Seafood",
    "vegetarian": "Vegetarian",
    "halal": "Halal",
    "barbecue": "Barbecue",
    "bbq": "Barbecue",
    "western food": "Western",
    "western": "Western",
    "japanese": "Japanese",
    "japanese food": "Japanese",
    "korean": "Korean",
    "korean food": "Korean",
    "recommended food": "recommended",
    "recommended": "recommended",
}

CUISINE_MAP_ZH = {
    "本地菜": "local",
    "当地美食": "local",
    "川菜": "Sichuan cuisine",
    "火锅": "hotpot",
    "茶馆": "Teahouse",
    "粤菜": "Cantonese cuisine",
    "点心": "Dim sum",
    "北京烤鸭": "Beijing roast duck",
    "面条": "Noodles",
    "饺子": "Dumplings",
    "海鲜": "Seafood",
    "素菜": "Vegetarian",
    "清真": "Halal",
    "烧烤": "Barbecue",
    "西餐": "Western",
    "日料": "Japanese",
    "韩餐": "Korean",
    "推荐美食": "recommended",
}

# 推荐/特色餐饮触发词
RECOMMENDED_FOOD_MARKERS_EN = [
    "try local", "local food", "recommended food", "must eat",
    "must try", "famous food", "specialty", "local cuisine",
]
RECOMMENDED_FOOD_MARKERS_ZH = [
    "推荐", "特色", "必吃", "当地美食", "一定要吃",
]
