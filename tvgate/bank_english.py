"""四年级下册英语仿真题生成器（人教 PEP 课标）。"""

import random

WORDS = [
    ("library", "图书馆"), ("playground", "操场"), ("garden", "花园"),
    ("teachers' office", "教师办公室"), ("art room", "美术教室"),
    ("music room", "音乐教室"), ("computer room", "计算机房"),
    ("first floor", "一楼"), ("second floor", "二楼"), ("classroom", "教室"),
    ("breakfast", "早餐"), ("lunch", "午餐"), ("dinner", "晚餐"),
    ("English class", "英语课"), ("music class", "音乐课"), ("PE class", "体育课"),
    ("get up", "起床"), ("go to school", "去上学"), ("go home", "回家"),
    ("go to bed", "上床睡觉"), ("sunny", "晴朗的"), ("cloudy", "多云的"),
    ("windy", "刮风的"), ("rainy", "下雨的"), ("snowy", "下雪的"),
    ("cold", "寒冷的"), ("warm", "温暖的"), ("hot", "炎热的"), ("cool", "凉爽的"),
    ("tomato", "西红柿"), ("potato", "土豆"), ("carrot", "胡萝卜"),
    ("green beans", "豆角"), ("horse", "马"), ("cow", "奶牛"), ("sheep", "绵羊"),
    ("hen", "母鸡"), ("farm", "农场"), ("animal", "动物"),
    ("coat", "外套"), ("shirt", "衬衫"), ("skirt", "短裙"), ("dress", "连衣裙"),
    ("sweater", "毛衣"), ("socks", "袜子"), ("shorts", "短裤"), ("pants", "裤子"),
    ("hat", "帽子"), ("shoes", "鞋子"), ("gloves", "手套"), ("scarf", "围巾"),
    ("umbrella", "雨伞"), ("sunglasses", "太阳镜"), ("pretty", "漂亮的"),
    ("cheap", "便宜的"), ("expensive", "昂贵的"), ("size", "尺码"),
    ("colour", "颜色"), ("shop", "商店"), ("buy", "买"), ("help", "帮助"),
    ("weather", "天气"), ("world", "世界"), ("ready", "准备好的"),
    ("careful", "小心的"), ("beautiful", "美丽的"), ("clean", "干净的"),
    ("homework", "家庭作业"), ("letter", "信"), ("picture", "图画"),
]

# (题干, 正确, [错误], 知识点, 难度, 解析)
GRAMMAR = [
    ("She ___ to school every day.", "goes", ["go", "going", "went"], "一般现在时", 1, "第三人称单数加 -es。"),
    ("He ___ to school every day.", "goes", ["go", "going", "went"], "一般现在时", 1, "第三人称单数加 -es。"),
    ("Tom ___ to school every day.", "goes", ["go", "going", "went"], "一般现在时", 1, "第三人称单数加 -es。"),
    ("My sister ___ to school every day.", "goes", ["go", "going", "went"], "一般现在时", 1, "第三人称单数加 -es。"),
    ("They ___ to school every day.", "go", ["goes", "going", "went"], "一般现在时", 1, "复数主语用动词原形。"),
    ("We ___ to school every day.", "go", ["goes", "going", "went"], "一般现在时", 1, "复数主语用动词原形。"),
    ("I ___ a student.", "am", ["is", "are", "be"], "一般现在时", 1, "I 用 am。"),
    ("You ___ a student.", "are", ["am", "is", "be"], "一般现在时", 1, "you 用 are。"),
    ("They ___ students.", "are", ["am", "is", "be"], "一般现在时", 1, "复数用 are。"),
    ("She ___ a teacher.", "is", ["am", "are", "be"], "一般现在时", 1, "第三人称单数用 is。"),
    ("Look! She ___ a book.", "is reading", ["read", "reads", "reading"], "现在进行时", 2, "Look! 提示现在进行时。"),
    ("Look! He ___ a book.", "is reading", ["read", "reads", "reading"], "现在进行时", 2, "Look! 提示现在进行时。"),
    ("Look! They ___ football.", "are playing", ["is playing", "play", "played"], "现在进行时", 2, "主语复数用 are playing。"),
    ("Look! I ___ my homework.", "am doing", ["is doing", "do", "does"], "现在进行时", 2, "I 用 am doing。"),
    ("Look! The children ___ in the garden.", "are playing", ["is playing", "play", "played"], "现在进行时", 2, "children 是复数。"),
    ("I ___ to the park yesterday.", "went", ["go", "goes", "going"], "一般过去时", 2, "yesterday 提示过去时。"),
    ("She ___ a cake last night.", "made", ["make", "makes", "making"], "一般过去时", 2, "last night 提示过去时。"),
    ("We ___ happy at the party.", "were", ["was", "are", "is"], "一般过去时", 2, "we 用 were。"),
    ("They ___ to the zoo last Sunday.", "went", ["go", "goes", "going"], "一般过去时", 2, "last Sunday 提示过去时。"),
    ("He ___ TV every evening.", "watches", ["watch", "watching", "watched"], "一般现在时", 2, "第三人称单数加 -es。"),
    ("My mother ___ dinner now.", "is cooking", ["cooks", "cook", "cooking"], "现在进行时", 2, "now 提示现在进行时。"),
    ("The cat is ___ the box.", "in", ["on", "under", "behind"], "介词", 1, "in 表示在……里面。"),
    ("The book is ___ the desk.", "on", ["in", "under", "behind"], "介词", 1, "on 表示在……上面。"),
    ("The ball is ___ the chair.", "under", ["in", "on", "behind"], "介词", 1, "under 表示在……下面。"),
    ("The tree is ___ the house.", "behind", ["in", "on", "under"], "介词", 2, "behind 表示在……后面。"),
    ("It's 7:00. It's time for ___.", "breakfast", ["lunch", "dinner", "bed"], "时间表达", 1, "7 点吃早餐。"),
    ("It's 12:00. It's time for ___.", "lunch", ["breakfast", "dinner", "bed"], "时间表达", 1, "12 点吃午餐。"),
    ("It's 9:00. It's time to ___.", "go to bed", ["get up", "go to school", "have breakfast"], "时间表达", 2, "9 点该睡觉。"),
    ("It's 6:30. It's time to ___.", "get up", ["go to bed", "go to school", "have dinner"], "时间表达", 2, "6:30 该起床。"),
    ("It's 7:30. It's time to ___.", "go to school", ["get up", "go to bed", "have dinner"], "时间表达", 2, "7:30 该上学。"),
    ("今天下雨。It's ___ today.", "rainy", ["sunny", "cloudy", "windy"], "天气", 1, "rainy 表示下雨。"),
    ("今天晴朗。It's ___ today.", "sunny", ["rainy", "cloudy", "windy"], "天气", 1, "sunny 表示晴朗。"),
    ("今天多云。It's ___ today.", "cloudy", ["sunny", "rainy", "windy"], "天气", 1, "cloudy 表示多云。"),
    ("今天刮风。It's ___ today.", "windy", ["sunny", "rainy", "cloudy"], "天气", 1, "windy 表示刮风。"),
    ("It's cold. Please ___.", "put on your coat", ["take off your coat", "put on your skirt", "take off your hat"], "天气", 2, "冷就穿上外套。"),
    ("It's hot. Please ___.", "take off your coat", ["put on your coat", "put on your hat", "put on your gloves"], "天气", 2, "热就脱下外套。"),
    ("How many ___ are there? — There are five.", "horses", ["horse", "horse's", "horsing"], "名词单复数", 1, "how many 后接复数。"),
    ("How many ___ are there? — There are three.", "cows", ["cow", "cow's", "cowing"], "名词单复数", 1, "how many 后接复数。"),
    ("There are two ___ on the farm.", "sheep", ["sheeps", "sheepe", "sheepes"], "名词单复数", 2, "sheep 的复数是 sheep。"),
    ("I like ___.", "tomatoes", ["tomato", "tomatos", "tomato's"], "名词单复数", 2, "tomato 复数加 -es。"),
    ("Can you ___?", "swim", ["swims", "swimming", "swam"], "情态动词", 1, "can 后接动词原形。"),
    ("She can ___ English.", "speak", ["speaks", "speaking", "spoke"], "情态动词", 1, "can 后接动词原形。"),
    ("Whose ___ is this? — It's mine.", "skirt", ["skirts", "skirt's", "skirting"], "购物", 1, "is this 用单数。"),
    ("Whose ___ are these? — They're mine.", "shoes", ["shoe", "shoe's", "shoing"], "购物", 2, "are these 用复数。"),
    ("How much ___ the skirt? — It's 50 yuan.", "is", ["are", "am", "be"], "购物", 2, "skirt 是单数用 is。"),
    ("How much ___ the shoes? — They're 80 yuan.", "are", ["is", "am", "be"], "购物", 2, "shoes 是复数用 are。"),
    ("This is ___ apple.", "an", ["a", "two", "the"], "冠词", 1, "apple 以元音音素开头用 an。"),
    ("I have ___ orange.", "an", ["a", "two", "the"], "冠词", 1, "orange 以元音音素开头用 an。"),
    ("There ___ a book on the desk.", "is", ["are", "am", "be"], "there be", 1, "单数用 is。"),
    ("There ___ two books on the desk.", "are", ["is", "am", "be"], "there be", 1, "复数用 are。"),
    ("He ___ football every Sunday.", "plays", ["play", "playing", "played"], "一般现在时", 2, "第三人称单数加 -s。"),
    ("We ___ TV now.", "are watching", ["is watching", "watch", "watches"], "现在进行时", 2, "now 提示现在进行时。"),
    ("She ___ her homework every day.", "does", ["do", "doing", "did"], "一般现在时", 2, "第三人称单数用 does。"),
    ("I ___ my homework yesterday.", "did", ["do", "does", "doing"], "一般过去时", 2, "yesterday 提示过去时。"),
    ("Look at the ___! They are cute.", "pandas", ["panda", "panda's", "pandes"], "名词单复数", 2, "they 指复数。"),
    ("My father ___ to work by car.", "goes", ["go", "going", "went"], "一般现在时", 2, "第三人称单数加 -es。"),
    ("My parents ___ to work by bus.", "go", ["goes", "going", "went"], "一般现在时", 2, "parents 是复数。"),
    ("___ do you get up? — At 6:30.", "When", ["What", "Where", "Who"], "疑问词", 2, "问时间用 When。"),
    ("___ is your favourite colour? — Blue.", "What", ["When", "Where", "Who"], "疑问词", 2, "问颜色用 What。"),
    ("___ is that man? — He's my father.", "Who", ["What", "When", "Where"], "疑问词", 1, "问人用 Who。"),
    ("___ are you? — I'm in the classroom.", "Where", ["What", "When", "Who"], "疑问词", 2, "问地点用 Where。"),
    ("___ books are these? — They're mine.", "Whose", ["Who", "What", "Where"], "疑问词", 2, "问所属用 Whose。"),
    ("I can see ___ elephant.", "an", ["a", "two", "the"], "冠词", 1, "elephant 以元音音素开头。"),
    ("Let's ___ a snowman.", "make", ["makes", "making", "made"], "祈使句", 2, "Let's 后接动词原形。"),
    ("It's time ___ lunch.", "for", ["to", "at", "in"], "时间表达", 2, "It's time for + 名词。"),
    ("It's time ___ go to school.", "to", ["for", "at", "in"], "时间表达", 2, "It's time to + 动词。"),
    ("The library is ___ the first floor.", "on", ["in", "at", "under"], "介词", 2, "楼层用 on。"),
    ("The art room is ___ the second floor.", "on", ["in", "at", "under"], "介词", 2, "楼层用 on。"),
    ("I go to school ___ 7:30.", "at", ["in", "on", "for"], "时间表达", 2, "具体时刻用 at。"),
    ("We have English ___ Monday.", "on", ["in", "at", "for"], "时间表达", 2, "具体某天用 on。"),
    ("She is ___ honest girl.", "an", ["a", "two", "the"], "冠词", 3, "honest 以元音音素开头。"),
    ("There ___ some milk in the glass.", "is", ["are", "am", "be"], "there be", 2, "milk 不可数用 is。"),
    ("There ___ some apples on the table.", "are", ["is", "am", "be"], "there be", 2, "apples 复数用 are。"),
    ("He doesn't ___ to school on Sunday.", "go", ["goes", "going", "went"], "一般现在时", 3, "doesn't 后接动词原形。"),
    ("She didn't ___ her homework yesterday.", "do", ["does", "did", "doing"], "一般过去时", 3, "didn't 后接动词原形。"),
    ("Are you ___ TV? — Yes, I am.", "watching", ["watch", "watches", "watched"], "现在进行时", 3, "be + doing。"),
    ("What ___ you doing? — I'm reading.", "are", ["is", "am", "do"], "现在进行时", 3, "you 用 are。"),
    ("___ she like apples? — Yes, she does.", "Does", ["Do", "Is", "Are"], "一般现在时", 3, "第三人称单数用 Does。"),
    ("___ they like apples? — Yes, they do.", "Do", ["Does", "Is", "Are"], "一般现在时", 3, "复数用 Do。"),
    ("This is ___ book. It's mine.", "my", ["I", "me", "mine"], "代词", 2, "my + 名词。"),
    ("The book is ___.", "mine", ["I", "me", "my"], "代词", 2, "mine 表示我的。"),
    ("These are ___ shoes.", "their", ["they", "them", "theirs"], "代词", 3, "their + 名词。"),
    ("The shoes are ___.", "theirs", ["they", "them", "their"], "代词", 3, "theirs 表示他们的。"),
]

# (题干, 正确, [错误], 解析)
DIALOGUE = [
    ("Can I help you? — ___", "Yes, I'd like a skirt.",
     ["No, you can't.", "I'm fine.", "Thank you."], "购物时的常用回答。"),
    ("Thank you. — ___", "You're welcome.",
     ["No, thanks.", "Yes, please.", "That's right."], "对感谢的回应。"),
    ("How are you? — ___", "I'm fine, thank you.",
     ["I'm ten.", "It's sunny.", "It's Monday."], "问候身体情况。"),
    ("What time is it? — ___", "It's 6 o'clock.",
     ["It's Sunday.", "It's sunny.", "It's red."], "问时间。"),
    ("What's the weather like? — ___", "It's sunny.",
     ["It's Monday.", "It's 6 o'clock.", "It's a book."], "问天气。"),
    ("What day is it today? — ___", "It's Monday.",
     ["It's sunny.", "It's 6 o'clock.", "It's red."], "问星期。"),
    ("Where is the library? — ___", "It's on the second floor.",
     ["It's Monday.", "It's sunny.", "It's 50 yuan."], "问地点。"),
    ("Is this your pencil? — ___", "Yes, it is.",
     ["Yes, I am.", "No, I don't.", "Yes, she is."], "一般疑问句回答。"),
    ("Do you like apples? — ___", "Yes, I do.",
     ["Yes, I am.", "No, I am not.", "Yes, she does."], "Do 引导的回答。"),
    ("What would you like? — ___", "I'd like some milk.",
     ["I am milk.", "I like to milk.", "Yes, please."], "表达想要什么。"),
    ("Let's go to the playground. — ___", "Great!",
     ["Thank you.", "You're welcome.", "I'm sorry."], "对建议的回应。"),
    ("How old are you? — ___", "I'm ten.",
     ["I'm fine.", "It's ten.", "I'm a student."], "问年龄。"),
    ("Where are you from? — ___", "I'm from China.",
     ["I'm ten.", "I'm fine.", "It's China."], "问来自哪里。"),
    ("What's this? — ___", "It's a cat.",
     ["He's a cat.", "She's a cat.", "They're a cat."], "问近处物品。"),
    ("Are these your books? — ___", "Yes, they are.",
     ["Yes, it is.", "Yes, I am.", "Yes, these are."], "复数一般疑问句回答。"),
    ("Happy birthday! — ___", "Thank you.",
     ["You're welcome.", "I'm sorry.", "Goodbye."], "对祝福的回应。"),
    ("Sorry, I'm late. — ___", "That's all right.",
     ["Thank you.", "You're welcome.", "Good idea."], "对道歉的回应。"),
    ("Let's have dinner. — ___", "OK, let's go.",
     ["Thank you.", "You're welcome.", "I'm sorry."], "对建议的回应。"),
    ("May I come in? — ___", "Come in, please.",
     ["Thank you.", "You're welcome.", "I'm sorry."], "请求进入的回应。"),
    ("Would you like some tea? — ___", "Yes, please.",
     ["Yes, I do.", "No, I don't.", "You're welcome."], "Would you like 的回答。"),
    ("What's your name? — ___", "My name is Amy.",
     ["I'm ten.", "I'm fine.", "It's Amy's."], "问名字。"),
    ("Nice to meet you. — ___", "Nice to meet you, too.",
     ["Thank you.", "You're welcome.", "Goodbye."], "初次见面的回应。"),
    ("Good morning. — ___", "Good morning.",
     ["Good night.", "Goodbye.", "Thank you."], "早上问候。"),
    ("Good night. — ___", "Good night.",
     ["Good morning.", "Good afternoon.", "Thank you."], "晚上告别。"),
    ("See you tomorrow. — ___", "See you.",
     ["Thank you.", "You're welcome.", "Good morning."], "告别用语。"),
    ("Can I have a look? — ___", "Sure, here you are.",
     ["Thank you.", "You're welcome.", "I'm sorry."], "请求看东西。"),
    ("Whose bag is this? — ___", "It's mine.",
     ["It's a bag.", "It's on the desk.", "It's 50 yuan."], "问所属。"),
    ("How much is it? — ___", "It's 50 yuan.",
     ["It's Monday.", "It's sunny.", "It's on the desk."], "问价格。"),
    ("What colour is it? — ___", "It's red.",
     ["It's a book.", "It's Monday.", "It's 50 yuan."], "问颜色。"),
    ("Where is my book? — ___", "It's on the desk.",
     ["It's red.", "It's mine.", "It's 50 yuan."], "问地点。"),
    ("Do you have any brothers? — ___", "Yes, I have one.",
     ["Yes, I am.", "No, I am not.", "Yes, she does."], "问是否有兄弟姐妹。"),
    ("What are these? — ___", "They're carrots.",
     ["It's a carrot.", "He's a carrot.", "She's a carrot."], "问复数物品。"),
    ("How many books do you have? — ___", "I have five.",
     ["I'm five.", "It's five.", "Yes, I do."], "问数量。"),
    ("Is she your sister? — ___", "Yes, she is.",
     ["Yes, he is.", "Yes, it is.", "Yes, I am."], "问女性。"),
    ("Is he your brother? — ___", "Yes, he is.",
     ["Yes, she is.", "Yes, it is.", "Yes, I am."], "问男性。"),
    ("What's the matter? — ___", "I have a cold.",
     ["I'm fine.", "Thank you.", "You're welcome."], "问怎么了。"),
    ("You look happy. — ___", "Yes, I am.",
     ["Thank you.", "You're welcome.", "Goodbye."], "描述情绪。"),
    ("Let's go home. — ___", "OK.",
     ["Thank you.", "You're welcome.", "I'm sorry."], "对建议的回应。"),
    ("Excuse me, where is the shop? — ___", "It's over there.",
     ["It's Monday.", "It's sunny.", "It's 50 yuan."], "问路。"),
    ("Have a nice day! — ___", "Thank you. You too.",
     ["You're welcome.", "I'm sorry.", "Good night."], "祝福的回应。"),
]

READING = [
    ("Hello! I'm Amy. I'm from England. I get up at 6:30. I have breakfast at 7:00. "
     "I go to school at 7:30. My school is big and beautiful. There is a library, "
     "a playground and a music room. I like my school very much.", [
        ("Where is Amy from?", "England", ["China", "America", "Australia"]),
        ("What time does Amy get up?", "6:30", ["7:00", "7:30", "6:00"]),
        ("What time does she have breakfast?", "7:00", ["6:30", "7:30", "8:00"]),
        ("What time does she go to school?", "7:30", ["6:30", "7:00", "8:00"]),
        ("Is Amy's school big?", "Yes, it is.", ["No, it isn't.", "Yes, she is.", "No, she isn't."]),
        ("What is in Amy's school?", "A library, a playground and a music room.",
         ["A library and a gym.", "A playground and a shop.", "A music room and a zoo."]),
        ("Does Amy like her school?", "Yes, she does.", ["No, she doesn't.", "Yes, he does.", "No, he doesn't."]),
        ("Amy is from ___.", "England", ["China", "Canada", "Japan"]),
        ("Amy has breakfast at ___.", "7:00", ["6:30", "7:30", "8:00"]),
        ("Which is NOT in Amy's school?", "A gym", ["A library", "A playground", "A music room"]),
     ]),
    ("It's Sunday. The weather is sunny and warm. Tom and his sister go to the farm. "
     "They see many animals. There are ten cows, eight horses and six sheep. The cows "
     "are big. The horses can run fast. Tom likes the horses. His sister likes the "
     "sheep. They are very happy.", [
        ("What day is it?", "Sunday", ["Monday", "Saturday", "Friday"]),
        ("What's the weather like?", "Sunny and warm", ["Rainy and cold", "Cloudy and cool", "Windy and hot"]),
        ("Where do Tom and his sister go?", "The farm", ["The zoo", "The park", "The school"]),
        ("How many cows are there?", "Ten", ["Eight", "Six", "Two"]),
        ("How many horses are there?", "Eight", ["Ten", "Six", "Two"]),
        ("How many sheep are there?", "Six", ["Ten", "Eight", "Two"]),
        ("What can the horses do?", "Run fast", ["Fly", "Swim", "Sing"]),
        ("What does Tom like?", "The horses", ["The cows", "The sheep", "The farm"]),
        ("What does his sister like?", "The sheep", ["The cows", "The horses", "The farm"]),
        ("How do they feel?", "Happy", ["Sad", "Angry", "Tired"]),
     ]),
]


def build():
    random.seed(20250403)
    out, seen = [], set()
    counter = [0]

    def add(kp, difficulty, stem, correct, distractors, explain=""):
        if stem in seen:
            return
        seen.add(stem)
        opts = [correct]
        for d in distractors:
            if d not in opts:
                opts.append(d)
        n = 1
        while len(opts) < 4:
            cand = "option %d" % n
            if cand not in opts:
                opts.append(cand)
            n += 1
        opts = opts[:4]
        random.shuffle(opts)
        counter[0] += 1
        out.append({
            "id": "g4e-%03d" % counter[0],
            "subject": "英语", "grade": 4, "kp": kp,
            "difficulty": difficulty, "stem": stem,
            "options": opts, "answer": opts.index(correct),
            "explain": explain,
        })

    # 词汇 60 题
    random.shuffle(WORDS)
    for english, chinese in WORDS[:60]:
        pool = [w[1] for w in WORDS if w[1] != chinese]
        random.shuffle(pool)
        add("词汇", 1, "“%s”的中文意思是？" % english, chinese, pool[:3],
            "结合单词记忆。")
    # 语法 80 题
    for stem, right, wrongs, kp, difficulty, explain in GRAMMAR:
        add(kp, difficulty, stem, right, wrongs, explain)
    # 情景交际 40 题
    for stem, right, wrongs, explain in DIALOGUE:
        add("情景交际", 2, stem, right, wrongs, explain)
    # 阅读 20 题
    for passage, questions in READING:
        for stem, right, wrongs in questions:
            full = "阅读短文，选择正确答案：\n\n%s\n\n%s" % (passage, stem)
            add("阅读理解", 3, full, right, wrongs, "回到短文中找依据。")

    return out
