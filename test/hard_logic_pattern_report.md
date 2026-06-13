# Hard Logic Pattern Report

Scanned: 1000 queries, 1000 with hard_logic_py

## Constraint Distribution

| Category | Count |
|----------|-------|
| must_visit_name | 5 |
| required_type | 37 |
| forbidden_type | 180 |
| free_attraction | 59 |
| day_count | 526 |
| people_count | 526 |
| intercity_transport | 73 |
| innercity_transport | 1164 |
| hotel_type | 84 |
| budget_dining | 104 |
| budget_accommodation | 90 |
| budget_total | 99 |
| cuisine_restaurant | 158 |
| unparsed | 463 |

## Transport Modes

- train: 52
- airplane: 43

## Hotel Types

- Free parking: 34
- Swimming pool: 8
- Sauna: 7
- Parking lot: 5
- Family Room: 4
- Charging station: 3
- Instagrammable swimming pool: 3
- Butler Service: 3
- 24-hour front desk: 2
- SPA: 2
- River view room: 2
- Mountain View Room: 1
- homestay: 1
- Fitness Room: 1
- Self-operated entertainment room: 1
- Media Room: 1
- Multifunction Hall: 1
- Family-themed Room: 1
- Laundry room: 1
- Great view from the window: 1
- Conference Hall: 1
- Lakeside Residence: 1

## Day Counts

- 2 days: 223
- 3 days: 174
- 4 days: 114
- 5 days: 15

## Budget Ranges

- dining: min=100, max=12900, avg=2666, n=104
- accommodation: min=400, max=28100, avg=3454, n=90
- total: min=1900, max=29100, avg=7399, n=99

## Sample Must-Visit Names (first 30)

- Iron Statue Temple Water Street
- Chongqing Haichang Caribbean Water World
- Four Seasons Ski Resort
- Tianfu Hibiscus Garden
- Four Seasons Ski Resort

## Sample Required Attraction Types (first 20)

- Museum/Memorial Hall
- park
- park
- Cultural Landscape
- Cultural Landscape
- Amusement Park/Sports Entertainment
- Museum/Memorial Hall
- commercial district
- historical site
- Amusement Park/Sports Entertainment
- commercial district
- park
- park
- Art Museum
- Cultural Landscape
- park
- Museum/Memorial Hall
- Amusement Park/Sports Entertainment
- Museum/Memorial Hall
- Amusement Park/Sports Entertainment

## Sample Forbidden Types

- All the Way Eating · Old Hangzhou Cuisine (Music Fountain Branch)
- Amusement Park/Sports Entertainment
- Art Museum
- Baguang Beach
- Catch Fish to Eat (South Ring New Village Branch)
- Chengdu Ritz-Carlton Hotel · FLAIR Restaurant and Bar
- Chongqing Happy Valley
- Chongqing International Trade Grandview Hotel - Grand Tea House
- Cultural Landscape
- Cultural Tourism Area
- Da Wu Yakiniku (Zhuoyue Center Branch)
- Eighteen Trees Imperial Tea Garden (Old Dragon Well Store)
- Free parking
- Gankeng Ancient Town
- Han Show Theater
- Holy Name Happy Water World
- Hot pot
- Hotel Apartment
- Kapok - Enchanting Cantonese Flavors (COCO Park Branch)
- Korean cuisine
- Lu's Soup Dumpling King (Changbai Street Branch)
- Manjushri Temple
- Mercure Shenzhen Nanshan Shenzhen Bay
- Museum/Memorial Hall
- Nanjing Train Paradise
- Nanxing Garden
- Oriental Green Boat Resort (Garden Hotel)
- Osmanthus Garden (Manjuelong Branch)
- Other
- Other Chinese Cuisine
- Qianhai Performance Park
- Rongchu Hubei Cuisine: Rib and Lotus Root Soup in a Clay Pot (Jianghan Road Branch 1)
- S Kitchen
- Seafood
- Self-operated family room
- Shanghai Tower Observation Deck
- Shenzhen Bay Park
- Shenzhen Museum of History and Folklore
- Shenzhen Park Hyatt Hotel · Yue Ting
- Shenzhen Penghui Raffles Hotel · Cloud View
- Sichuan cuisine
- Smart toilet
- Snacks
- South Pavilion Tea House Private Custom Tea Banquet
- Squirrel Kaka Forest Park
- Sunbathing area
- Taiping Heavenly Kingdom History Museum (Zhan Garden)
- The Ritz-Carlton Shanghai, Pudong - Scena di Angelo
- URBN Boutique Shanghai
- West Dyke Thick Steak (Yuanrong Branch)
- Wuhan Zoo
- Xiyue Mountain Residence Artisan Creative Cuisine (Yiyuan Road Branch)
- Yue Bai Wei · Premium Sichuan Cuisine (UPARK Park Branch)
- Yunnan cuisine
- buffet
- cafe
- commercial district
- fusion cuisine
- metro
- red tourism sites
- taxi
- university campus
- walk

## Unparsed Snippets (first 20)

- `attraction_cost=0
for activity in allactivities(plan):
  if activity_type(activity)=='attraction': attraction_cost+=activity_cost(activity)
result=att`
- `attraction_cost=0
for activity in allactivities(plan):
  if activity_type(activity)=='attraction': attraction_cost+=activity_cost(activity)
result=att`
- `attraction_cost=0
for activity in allactivities(plan):
  if activity_type(activity)=='attraction': attraction_cost+=activity_cost(activity)
result=att`
- `accommodation_name_set=set()
for activity in allactivities(plan):
  if activity_type(activity)=='accommodation': accommodation_name_set.add(activity_p`
- `accommodation_name_set=set()
for activity in allactivities(plan):
  if activity_type(activity)=='accommodation': accommodation_name_set.add(activity_p`
- `accommodation_name_set=set()
for activity in allactivities(plan):
  if activity_type(activity)=='accommodation': accommodation_name_set.add(activity_p`
- `accommodation_name_set=set()
for activity in allactivities(plan):
  if activity_type(activity)=='accommodation': accommodation_name_set.add(activity_p`
- `accommodation_name_set=set()
for activity in allactivities(plan):
  if activity_type(activity)=='accommodation': accommodation_name_set.add(activity_p`
- `accommodation_name_set=set()
for activity in allactivities(plan):
  if activity_type(activity)=='accommodation': accommodation_name_set.add(activity_p`
- `inter_city_transportation_cost=0
for activity in allactivities(plan):
  if activity_type(activity) in ['airplane','train']: inter_city_transportation_`
- `inter_city_transportation_cost=0
for activity in allactivities(plan):
  if activity_type(activity) in ['airplane','train']: inter_city_transportation_`
- `inter_city_transportation_cost=0
for activity in allactivities(plan):
  if activity_type(activity) in ['airplane','train']: inter_city_transportation_`
- `inter_city_transportation_cost=0
for activity in allactivities(plan):
  if activity_type(activity) in ['airplane','train']: inter_city_transportation_`
- `inter_city_transportation_cost=0
for activity in allactivities(plan):
  if activity_type(activity) in ['airplane','train']: inter_city_transportation_`
- `inter_city_transportation_cost=0
for activity in allactivities(plan):
  if activity_type(activity) in ['airplane','train']: inter_city_transportation_`
- `result=False
for activity in allactivities(plan):
  if activity_position(activity)=='Huì Tíng · Jīng Cuì (LaLaport Store)':
    if activity_time(activ`
- `result=True
for activity in allactivities(plan):
  if activity_type(activity)=='accommodation' and room_type(activity)!=2: result=False`
- `result=True
for activity in allactivities(plan):
  if activity_type(activity)=='accommodation' and room_type(activity)!=1: result=False`
- `result=True
for activity in allactivities(plan):
  if activity_type(activity)=='accommodation' and room_type(activity)!=2: result=False`
- `result=True
for activity in allactivities(plan):
  if activity_type(activity)=='accommodation' and room_type(activity)!=1: result=False`
