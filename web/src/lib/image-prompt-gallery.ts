export type ImagePromptGalleryCategory = "portrait" | "poster" | "character" | "ui" | "creative";

export type ImagePromptGalleryItem = {
  id: string;
  category: ImagePromptGalleryCategory;
  title: string;
  summary: string;
  prompt: string;
  previewImageUrl: string;
  sourceTitle: string;
  sourceUrl: string;
  creator: string;
};

export const IMAGE_PROMPT_GALLERY_SOURCE_URL =
  "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md";

const IMAGE_PREVIEW_BASE_URL =
  "https://raw.githubusercontent.com/EvoLinkAI/awesome-gpt-image-2-prompts/main/images";

export const IMAGE_PROMPT_GALLERY_CATEGORIES = [
  { value: "all", label: "全部", badge: "ALL" },
  { value: "portrait", label: "人像", badge: "PORTRAIT" },
  { value: "poster", label: "海报", badge: "POSTER" },
  { value: "character", label: "角色", badge: "CHARACTER" },
  { value: "ui", label: "UI", badge: "UI" },
  { value: "creative", label: "创意", badge: "CREATIVE" },
] as const;

export type ImagePromptGalleryFilter = (typeof IMAGE_PROMPT_GALLERY_CATEGORIES)[number]["value"];

export const IMAGE_PROMPT_GALLERY_ITEMS: ReadonlyArray<ImagePromptGalleryItem> = [
  {
    id: "portrait-cinematic-minimal",
    category: "portrait",
    title: "极简电影感肖像",
    summary: "单人站在红橙渐变空间里，用强烈剪影和高对比阴影做出海报级氛围。",
    prompt:
      "Generate a cinematic minimal portrait of a solitary man standing in an intense orange to red gradient environment, strong silhouette lighting, deep shadow contrast, reflective glossy floor, symmetrical composition, minimal",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/portrait_case2/output.jpg`,
    sourceTitle: "Cinematic Minimal Portrait",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-2-cinematic-minimal-portrait-by-iam_miharbi",
    creator: "@iam_miharbi",
  },
  {
    id: "portrait-skatepark-snapshot",
    category: "portrait",
    title: "名人快照一句话生图",
    summary: "用极短 prompt 做真实街拍抓拍，适合测试模型对人物与场景关系的理解。",
    prompt: '"Sam Altman on a skateboard at a skatepark with no people."',
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/portrait_case10/output.jpg`,
    sourceTitle: "Sam Altman Skatepark Snapshot",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-10-sam-altman-skatepark-snapshot-by-malek1173989",
    creator: "@Malek1173989",
  },
  {
    id: "poster-amalfi-travel",
    category: "poster",
    title: "复古阿马尔菲旅行海报",
    summary: "复古旅行招贴的高饱和插画写法，适合城市、景区和文旅主题。",
    prompt: `Modern pencil illustration of Vintage travel poster illustration of the Amalfi Coast, Italy, panoramic coastal cliff road scene, classic 1960s white car driving along a curved seaside road, deep blue Mediterranean sea with small sailboats, colorful pastel hillside village, bright blue sky with soft clouds, lemon tree branches with vibrant yellow lemons framing the foreground, warm summer sunlight, bold vibrant colors, retro 1950s travel poster style, cinematic composition, high detail, screen print texture, graphic illustration. Hand-drawn style, illustration with loose strokes and defined contours. High-contrast color palette, maintaining chromatic harmony between background and elements. Contemporary and decorative aesthetic.`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case2/output.jpg`,
    sourceTitle: "Vintage Amalfi Travel Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-2-vintage-amalfi-travel-poster-by-wolfriccardo",
    creator: "@WolfRiccardo",
  },
  {
    id: "poster-food-map",
    category: "poster",
    title: "城市美食地图插画",
    summary: "把城市地图、地标和手绘食物插画做成一张信息量很高的主题海报。",
    prompt: `一张手绘风格的城市美食地图，以成都为主题。画面以鸟瞰视角的手绘简化城市地图为底，标注主要道路和地标但不追求精确比例而是追求可爱的手绘感。地图上分布着 12 个美食地点的精致手绘小插画：春熙路的串串香（一把竹签插着各种食材冒着热气）、宽窄巷子的三大炮（三个糯米团子飞向铜盘）、建设路的蛋烘糕（金黄酥脆正在翻面）、玉林路的火锅（九宫格锅翻滚冒泡）等，每个插画约占地图的 5% 面积，旁边用手写体标注店名和一句推荐语"凌晨两点还在排队的那家"。地图边缘用手绘藤蔓和辣椒装饰形成边框。右下角有一个手绘指南针和图例说明。左上角标题"成都·吃货暴走地图"使用胖圆的手绘美术字配辣椒装饰。整体画风为水彩+彩铅混合的手绘质感，颜色以暖色系（辣椒红、姜黄、翠绿）为主，图片比例 1:1。`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case3/output.jpg`,
    sourceTitle: "Chengdu Food Map Illustration",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-3-chengdu-food-map-illustration-by-panda20230902",
    creator: "@Panda20230902",
  },
  {
    id: "character-reference-card",
    category: "character",
    title: "角色设定资料卡",
    summary: "把参考角色整理成官方设定集风格的资料卡，适合角色世界观和立绘整理。",
    prompt: `基于此角色和背景，请制作一份类似官方设定资料的角色资料卡。
・包含三视图：正面、侧面和背面
・添加角色面部表情的变化・分解并展示服装和装备的详细部分
・添加色板・包含世界观设定的简要说明
・总体上，使用有组织的布局（白色背景，插画风格）高分辨率、专业概念艺术风格`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/character_case2/output.jpg`,
    sourceTitle: "Persona5 Character Reference Card",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-2-persona5-character-reference-card-by-iamrednights",
    creator: "@iamrednightS",
  },
  {
    id: "character-official-sheet",
    category: "character",
    title: "官方角色三视图设定表",
    summary: "适合把已有角色转成三视图、表情、配色和装备拆解页。",
    prompt: `このキャラクターと背景を元に、 公式設定資料のようなキャラクターシートを作成してください。
・正面、側面、背面の3面図を含める ・キャラクターの表情バリエーションを追加
・衣装や装備の詳細パーツを分解して表示 ・カラーパレットを追加 ・世界観の簡単な説明を入れる
・全体は整理されたレイアウト
（白背景、図解風）
・アスペクト比16：9

高解像度、プロのコンセプトアートスタイル`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/character_case5/output.jpg`,
    sourceTitle: "Official Character Sheet (JP)",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-5-official-character-sheet-jp-by-toshi_nyaruo_ai",
    creator: "@Toshi_nyaruo_AI",
  },
  {
    id: "ui-one-prompt-system",
    category: "ui",
    title: "一句话 UI 设计系统",
    summary: "把同一种视觉风格扩展成网页、移动端、卡片、按钮和控件整套系统。",
    prompt: "用这种风格帮我生成一套UI设计系统，包含网页、移动端、卡片、控件、按钮 以及其它",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case1/output.jpg`,
    sourceTitle: "One-Prompt UI Design Generation",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-1-one-prompt-ui-design-generation-by-austinit",
    creator: "@austinit",
  },
  {
    id: "ui-glassy-system",
    category: "ui",
    title: "Glassy 设计系统",
    summary: "适合快速做玻璃拟态、透明叠层、前卫视觉的 UI 概念图。",
    prompt: "Generate for me a UI design system with a very cutting-edge, bold, and unique theme that includes glassy visuals and transparencies",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case26/output.jpg`,
    sourceTitle: "Glassy UI Design System",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-26-glassy-ui-design-system-by-pfanis",
    creator: "@pfanis",
  },
  {
    id: "creative-silhouette-universe",
    category: "creative",
    title: "轮廓宇宙叙事海报",
    summary: "让主题世界长在某个象征性轮廓里，适合做收藏版叙事海报。",
    prompt: `请根据【主题：xxx】自动生成一张高审美的“轮廓宇宙 / 收藏版叙事海报”风格作品。不要将画面局限于固定器物或常见容器，不要优先默认瓶子、沙漏、玻璃罩、怀表之类的常规载体，而是由 AI 根据主题自行判断并选择一个最契合、最有象征意义、轮廓最强、最适合承载完整叙事世界的主轮廓载体。这个主轮廓可以是器物、建筑、门、塔、拱门、穹顶、楼梯井、长廊、雕像、侧脸、眼睛、手掌、头骨、羽翼、面具、镜面、王座、圆环、裂缝、光幕、阴影、几何结构、空间切面、舞台框景、抽象符号或其他更有创意与主题代表性的视觉轮廓，要求合理布局。

画面的核心不是简单把世界装进某个物体里，而是让完整的主题世界自然生长在这个主轮廓之中、之内、之上、之边界里或与其结构融为一体，形成一种“主题宇宙依附于一个象征性轮廓展开”的高级叙事效果。主轮廓必须清晰、优雅、有辨识度，并在整体构图中占据核心地位。

整体构图需要具有强烈的收藏版海报气质与高级设计感，大结构稳定，主轮廓强烈明确，内部世界具有纵深、秩序和呼吸感，细节丰富但不拥挤，内容丰满但不杂乱，可以适度加入小比例人物剪影、远处建筑、光柱、门洞、桥、阶梯、回廊、倒影、天光或远景结构来增强尺度感、故事感与史诗感。

最终要求：第一眼有强烈的主题识别度和轮廓记忆点，第二眼有完整丰富的叙事世界，第三眼仍有细节和余味。`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/comparison_case23/output.jpg`,
    sourceTitle: "Silhouette Universe Narrative Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-23-silhouette-universe-narrative-poster-by-mrlarus",
    creator: "@MrLarus",
  },
  {
    id: "creative-cinematic-infographic",
    category: "creative",
    title: "信息图式电影海报",
    summary: "只有一个主题变量，其余视觉结构、隐喻、排版都交给模型自动推导。",
    prompt: `请围绕【主题】自动生成一张顶级概念海报 / 信息图式电影海报。

唯一输入变量只有:
【主题】:__中国历史上的皇帝排名_

要求 AI 根据这个主题,自动推导并统一设计以下全部视觉系统,不需要我额外指定:
- 核心主体(可以自动判断更适合人物、产品、建筑、器物、符号、场景或抽象意象)
- 底部支撑结构
- 上方悬浮符号或精神象征
- 场景包裹元素
- 隐喻系统
- 色彩层级
- 材质对比
- 光影逻辑
- 标题、副标题、辅助文案
- 品牌感与高级感表达方式

最终画面必须是:
一张震撼、精密、统一、电影级、超高细节、可用于高端印刷的概念主视觉海报。`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case56/output.jpg`,
    sourceTitle: "Cinematic Infographic Concept Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-56-cinematic-infographic-concept-poster-by-a9quant",
    creator: "@A9Quant",
  },
  {
    id: "poster-boston-spring-2026",
    category: "poster",
    title: "波士顿春季城市海报",
    summary: "用河流笔触把城市地标串进同一条视觉主线，适合城市形象和文旅主视觉。",
    prompt:
      "A striking Spring 2026 city poster for Boston with an elegant celebratory mood and a bold contemporary design. On a clean off-white textured background with large areas of negative space, a miniature single sculler rows across the lower right corner of the image on a narrow ribbon of reflective water. The wake from the oar sweeps upward in a dynamic calligraphic curve, gradually transforming into the Charles River and then into a dreamlike hand-painted panorama of Boston. Inside this flowing river-shaped composition are iconic Boston elements: the Back Bay skyline, Beacon Hill brownstones, Acorn Street, Boston Public Garden, Swan Boats, Zakim Bridge, Fenway-inspired details, historic brick architecture, harbor ferries, and the city's waterfront atmosphere. Soft morning fog, golden spring light, subtle festive accents in crimson and gold, rich detail, layered depth, sophisticated city-poster aesthetics, fresh and refined, visually powerful but not overcrowded. Elegant typography in the lower left reads “SPRING 2026” with a vertical slogan “BOSTON, A CITY OF RIVER, MEMORY, AND INVENTION”, text clear and beautifully composed, premium graphic design, 9:16",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case1/output.jpg`,
    sourceTitle: "Boston Spring 2026 City Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-1-boston-spring-2026-city-poster-by-bubblebrain",
    creator: "@BubbleBrain",
  },
  {
    id: "poster-doodle-ai-builder",
    category: "poster",
    title: "涂鸦速写 AI Builder",
    summary: "夸张线条和留白结合的草稿海报，适合人物概念、海报草图和创意签名风格。",
    prompt:
      "以涂鸦速写风表现【一个厉害的AI builder】，整体呈现快速勾勒、自由变形、即兴手绘与草稿式的视觉效果。线条随手、夸张、可粗细不一，略显凌乱但具有节奏和表现力，强调概括、夸张、趣味和随性，而不是严谨写实或精细刻画。颜色采用粗糙、干刷感明显的块面表现，可保留不均匀的涂抹痕迹、刷痕、飞白与覆盖感，色彩根据【主题/主体】自动适配，但整体保持涂鸦式、速写式、概括式的表达。背景以留白为主，保持简洁、轻松、未完成感和设计感，可加入少量辅助性符号、箭头、记号、圈画、重复线、随手写的文字或其他涂鸦元素。画面内容不需要预先写清楚，由【一个厉害的AI builder】自动推演主体形象、动作与相关元素，整体保持统一的涂鸦速写风。画面中需自然加入专属签名“BlanPlan”，位置低调但清晰。",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case7/output.jpg`,
    sourceTitle: "Doodle Sketch AI Builder",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-7-doodle-sketch-ai-builder-by-blanplan",
    creator: "@blanplan",
  },
  {
    id: "ui-japanese-rpg-status",
    category: "ui",
    title: "日式 RPG 状态界面",
    summary: "把现有视觉主题转成信息量很高的日式游戏状态页，适合 HUD、角色面板和系统 UI。",
    prompt: "この画像からゲームのステータス画面を作ってください。情報量多め。言語は日本語。",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case27/output.jpg`,
    sourceTitle: "Japanese RPG Status Screen",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-27-japanese-rpg-status-screen-by-kashiko_aiart",
    creator: "@Kashiko_AIart",
  },
  {
    id: "ui-xuanwu-gate-social-feed",
    category: "ui",
    title: "历史事件朋友圈界面",
    summary: "把历史题材直接变成社交 feed，适合做戏仿型 UI、历史传播和叙事界面概念。",
    prompt: "玄武门之变的朋友圈",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case28/output.jpg`,
    sourceTitle: "Xuanwu Gate Social Feed",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-28-xuanwu-gate-social-feed-by-tz_2022",
    creator: "@Tz_2022",
  },
  {
    id: "ui-city-travel-guide",
    category: "ui",
    title: "城市三天旅游攻略",
    summary: "一句话生成完整旅行信息图，适合景点清单、路线卡片和轻量导览页。",
    prompt: "生成【城市】三天旅游攻略,就这么简单一句话",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case29/output.jpg`,
    sourceTitle: "City Travel Guide Infographic",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-29-city-travel-guide-infographic-by-mrlarus",
    creator: "@MrLarus",
  },
  {
    id: "ui-3d-x-profile-mockup",
    category: "ui",
    title: "3D 社媒主页破框海报",
    summary: "把个人主页做成带破框人物的 3D 社交页面，适合头像页、个人品牌页和宣传图。",
    prompt:
      "创作一幅超逼真的 3D 插画,描绘一个略微倾斜的 Twitter/X 个人资料页面,背景为简洁的灰色。保留原有的卡通头像。界面必须与真实的 X 截图相似,包含真实的布局、认证徽章、粉丝统计、个人资料横幅和推文部分。个人资料详情: 一位时尚的年轻男子,有着蓬松的亮黑色短发和白皙的皮肤,从个人资料页面的右侧撕开的纸片中跃然而出。他保留了原有的面部特征,只是将表情改为自然自信的微笑。他握着撕开的纸片边缘,纸屑四处飞溅,营造出强烈的 3D 突破效果。柔和的影棚灯光、电影级的阴影、景深、超高细节、清晰的焦点、逼真的皮肤、逼真的 UI 反射、优质的构图、4K 分辨率、逼真与微妙的皮克斯风格融合。重要提示: 请勿更改头像；保持 X UI 界面准确；保留原有的面部特征；角色为男性；仅增强笑容；确保所有中文文字清晰易读。",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case30/output.jpg`,
    sourceTitle: "3D X Profile Mockup",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-30-3d-x-profile-mockup-by-gosailglobal",
    creator: "@GoSailGlobal",
  },
  {
    id: "creative-dreamy-watercolor-editorial",
    category: "creative",
    title: "梦幻水彩编辑插画",
    summary: "极简题材也能做出柔和的纸感和空气感，适合插画封面、轻 editorial 和儿童书风格探索。",
    prompt:
      "Ilustración en acuarela de estilo onírico de [sujeto], con estética impresionista ligera, pinceladas sueltas y lavados translúcidos en tonos [color1] y [color2]. Difuminado suave sobre textura de papel prensado en frío, iluminación delicada, composición limpia, enfoque minimalista, sensación de calma, ligereza y belleza efímera, alta calidad, estilo editorial.",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case31/output.jpg`,
    sourceTitle: "Dreamy Watercolor Editorial Illustration",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-31-dreamy-watercolor-editorial-illustration-by-hmontilla_",
    creator: "@hmontilla_",
  },
  {
    id: "poster-science-encyclopedia-infographic",
    category: "poster",
    title: "科普百科竖版信息图",
    summary: "更偏知识卡和图鉴布局，适合动植物、产品、材料或概念主题的一页式百科图。",
    prompt: `请根据【主题】生成一张高质量竖版「科普百科图」。

这张图不是普通海报,也不是单纯插画,而是一张兼具“图鉴感、百科感、信息结构感、收藏感”的模块化科普信息图。整体风格参考高级博物图鉴、现代百科书页、生活方式知识卡和社交媒体高传播信息图的结合。

请让画面包含:
- 一个清晰漂亮的主题主视觉
- 若干局部特征放大细节
- 多个圆角模块化信息分区
- 清楚的标题层级与重点标签
- 简洁但丰富的百科内容
- 可视化评分、要点总结或 Top 5 模块

内容栏目请根据主题自动适配,优先从这些方向中选择并合理组合:
基础档案、分类信息、外观特征、习性/生态、形成机制/结构组成、生长或使用条件、养护或维护建议、风险与注意事项、适合人群或适用场景、优缺点对比、快速评分卡。

视觉要求:
浅色干净背景,柔和配色,轻阴影,精致小图标,圆角信息框,整洁排版,信息密度高但不拥挤,阅读体验好。整体必须像真正可以发布、阅读、收藏、系列化生产的科普百科卡,而不是广告图。`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case39/output.jpg`,
    sourceTitle: "Science Encyclopedia Infographic",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-39-science-encyclopedia-infographic-by-mrlarus",
    creator: "@MrLarus",
  },
  {
    id: "poster-silicon-valley-2026",
    category: "poster",
    title: "硅谷 2026 城市宣传海报",
    summary: "延续城市品牌海报路线，把科技地标、地形和数据流揉进一条发光主线里。",
    prompt:
      "A refined 2026 Silicon Valley city promotional poster with a futuristic yet elegant atmosphere. Double exposure composition, preserving an S-shaped sense of flowing movement. On a pure white textured background, in the lower-right corner, a miniature figure dressed in sleek modern techwear is releasing a long ribbon of luminous silver-blue light. The ribbon flows gracefully through the air, showing a soft silk-like texture, and as it drifts toward the upper-left, it magically transforms into a grand landscape of rolling hills, coastline, data streams, and illuminated urban terrain. Within this flowing river of light, overlay a hand-drawn panoramic map of Silicon Valley, blending technology, nature, innovation, and California sunlight. Include iconic Silicon Valley and Bay Area elements: Stanford University arches, Apple Park, Google campus-inspired buildings, Meta-like glass offices, Tesla-style innovation imagery, venture capital offices on Sand Hill Road, Palo Alto tree-lined streets, San Jose skyline, the Santa Cruz Mountains, San Francisco Bay, highways, autonomous vehicles, startup labs, semiconductor patterns, AI data centers, and subtle circuit-board textures. Elegant typography reads “SILICON VALLEY 2026” with a vertical slogan “Where Ideas Shape Tomorrow.” Premium city branding poster, cinematic lighting, 9:16 aspect ratio.",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case48/output.jpg`,
    sourceTitle: "Silicon Valley 2026 Promo Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-48-silicon-valley-2026-promo-poster-by-carsonyungos",
    creator: "@carsonyungos",
  },
  {
    id: "ui-cyberpunk-neon-system",
    category: "ui",
    title: "赛博霓虹 UI 设计系统",
    summary: "直接生成紫蓝粉霓虹系 dashboard 与移动端套件，适合高科技感和夜景氛围方向。",
    prompt:
      "用未来都市风格生成UI设计系统,灵感来自赛博朋克城市夜景,包含霓虹灯、玻璃建筑反射、高对比光影,配色以紫色、蓝色、粉色霓虹为主,设计网页Dashboard、移动端界面、卡片、按钮、控件等,视觉炫酷、层次丰富、科技感极强",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case38/output.jpg`,
    sourceTitle: "Cyberpunk Neon UI Design System",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-38-cyberpunk-neon-ui-design-system-by-azlnfvp",
    creator: "@AZLnfvp",
  },
  {
    id: "creative-calligraphy-copybook",
    category: "creative",
    title: "书法临摹字帖",
    summary: "一句话就能把任意字体主题转成临摹纸，适合做字形练习、文化周边和排版灵感。",
    prompt: "生成一张【字体】书法临摹字帖",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case33/output.jpg`,
    sourceTitle: "Calligraphy Copybook Sheet",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-33-calligraphy-copybook-sheet-by-mrlarus",
    creator: "@MrLarus",
  },
  {
    id: "poster-science-vertical",
    category: "poster",
    title: "科普百科竖版主视觉",
    summary: "一句英文模板快速起科普主视觉，适合先做主题探索，再逐步往百科卡细化。",
    prompt: "Generate a high-quality vertical science popularization encyclopedia image based on [Theme].",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case32/output.jpg`,
    sourceTitle: "Science Encyclopedia Vertical Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-32-science-encyclopedia-vertical-poster-by-pfanis",
    creator: "@pfanis",
  },
  {
    id: "poster-character-relationship-map",
    category: "poster",
    title: "人物关系图海报",
    summary: "适合小说、影视、游戏阵营或家族谱系，一句主题就能先起关系图版式。",
    prompt: "请根据【主题】生成一张高设计感的人物关系图海报。",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case34/output.jpg`,
    sourceTitle: "Character Relationship Map Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-34-character-relationship-map-poster-by-mrlarus",
    creator: "@MrLarus",
  },
  {
    id: "poster-new-chinese-ink",
    category: "poster",
    title: "新中式水墨山水海报",
    summary: "适合东方极简和大留白路线，主题词替换后可快速做意境类海报。",
    prompt: "新中式水墨山水海报，竖版9:16构图，东方极简美学风格，大面积留白，主题是春岚一叶红。",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case35/output.jpg`,
    sourceTitle: "New Chinese Ink Landscape Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-35-new-chinese-ink-landscape-poster-by-liyue_ai",
    creator: "@liyue_ai",
  },
  {
    id: "creative-journey-west-comic",
    category: "creative",
    title: "西游题材连环画",
    summary: "短 prompt 就能出小人书方向，适合中国叙事、国风漫画和故事分镜灵感。",
    prompt: "以中国连环画（小人书）的风格帮我绘制大闹天空",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case33/output.jpg`,
    sourceTitle: "Journey to the West Chinese Comic",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-33-journey-to-the-west-chinese-comic-by-overseas58",
    creator: "@overseas58",
  },
  {
    id: "creative-sony-exploded-view",
    category: "creative",
    title: "相机爆炸图拆解",
    summary: "适合产品结构图、工业设计说明和爆炸图海报，做器物分解特别直接。",
    prompt: "Descomposición detallada de una cámara de la marca Sony modelo A7 indicando todas sus piezas y con sus nombres.",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case53/output.jpg`,
    sourceTitle: "Sony A7 Exploded View Breakdown Prompt",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-53-sony-a7-exploded-view-breakdown-prompt-by-iapulse_",
    creator: "@iaPulse_",
  },
  {
    id: "poster-fictional-anime-movie",
    category: "poster",
    title: "架空动画电影海报",
    summary: "适合先起一个日系电影海报方向，再逐步补世界观、角色和 tagline。",
    prompt: "架空のアニメ映画のポスターをGPT image2で作成。",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case40/output.jpg`,
    sourceTitle: "Fictional Anime Movie Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-40-fictional-anime-movie-poster-by-seiiiiiiiiiiru",
    creator: "@seiiiiiiiiiiru",
  },
  {
    id: "poster-donki-pop-ad",
    category: "poster",
    title: "唐吉诃德卖场 Pop 广告",
    summary: "快速生成日本卖场促销海报的密集排版和强促销气质，适合商品广告和线下贴纸风格。",
    prompt: "GPT Image 2を使って、OpenClawの情報を調べてドンキの広告ポップ風に実際のドンキに貼っているような感じで画像生成してください",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case34/output.jpg`,
    sourceTitle: "Don Quijote Promo Pop Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-34-don-quijote-promo-pop-poster-by-loglogrog",
    creator: "@loglogrog",
  },
  {
    id: "ui-japanese-gacha-screen",
    category: "ui",
    title: "日式抽卡界面",
    summary: "超短 prompt 但风格明确，适合游戏抽卡、转盘和稀有度展示界面起稿。",
    prompt: "日本のソシャゲのガチャ画面を生成して、",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case35/output.jpg`,
    sourceTitle: "Japanese Gacha Game Screen",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-35-japanese-gacha-game-screen-by-the_wheel_2024",
    creator: "@the_wheel_2024",
  },
  {
    id: "ui-ai-game-dev-slide",
    category: "ui",
    title: "AI 游戏开发概览幻灯片",
    summary: "适合做横版单页报告、技术概览页和复杂信息的一页式演示稿。",
    prompt:
      "横長のパワポ画像ここで生成してみて　どのモデル使ってるか判定するから、今のAIゲーム開発の概要をまとめた1枚パワポで　日本語で\n\nゲーム開発の技術に関して、工数ベースでどこにパワーかかるかの分析資料といかに量産が大事かについての説明とかのパワポ画も作って",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case40/output.jpg`,
    sourceTitle: "Japanese AI Game Dev Overview Slide Prompt",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-40-japanese-ai-game-dev-overview-slide-prompt-by-ailovedirector",
    creator: "@ailovedirector",
  },
  {
    id: "creative-personal-profile-infographic",
    category: "creative",
    title: "个人档案漫画信息图",
    summary: "适合把人物设定、创作者介绍或个人履历做成轻松的漫画式信息图。",
    prompt: "Wykorzystaj wszystko, co o mnie wiesz, i stwórz infografikę przedstawiającą mnie. Zrób to w stylu komiksu franko-belgijskiego.",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/comparison_case45/output.jpg`,
    sourceTitle: "Personal Profile Infographic",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-45-personal-profile-infographic",
    creator: "@icreatelife",
  },
  {
    id: "poster-west-lake-travel",
    category: "poster",
    title: "杭州西湖旅游海报",
    summary: "一句话直出文旅宣传海报，适合城市景点、文旅项目和地标活动主视觉。",
    prompt: "帮我生成一个介绍杭州西湖的海报",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case63/output.jpg`,
    sourceTitle: "Hangzhou West Lake Travel Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-63-hangzhou-west-lake-travel-poster",
    creator: "@BNBOKBt5",
  },
  {
    id: "poster-dongfang-bubai-wuxia",
    category: "poster",
    title: "东方不败武侠角色海报",
    summary: "适合武侠角色定妆、概念海报和东方奇情氛围图，一条 prompt 可衍生多张角色海报。",
    prompt: `图片1：电影角色海报，东方不败红衣饮酒，悬崖落日，武侠意境

图片2：东方不败绣花针如飞，红衣长发立于悬崖，黑木崖夕阳如血`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case64/output.jpg`,
    sourceTitle: "Dongfang Bubai Wuxia Character Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-64-dongfang-bubai-wuxia-character-poster",
    creator: "@songguoxiansen",
  },
  {
    id: "creative-istiklal-panorama",
    category: "creative",
    title: "历史街景全景图",
    summary: "适合老城复原、场景设定和沉浸式地图，全景图方向很适合世界观铺陈。",
    prompt: "360 equirectangular image of Istiklal Street, Istanbul in 1900",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case54/output.jpg`,
    sourceTitle: "1900 Istiklal Street Panorama Prompt",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-54-1900-istiklal-street-panorama-prompt-by-ai_gezgini",
    creator: "@ai_gezgini",
  },
  {
    id: "creative-chili-pork-flowchart",
    category: "creative",
    title: "辣椒炒肉流程图",
    summary: "适合菜谱图、流程拆解卡和小红书图文，一句 prompt 就能起真实流程图版式。",
    prompt: "帮我制作辣椒炒肉这道菜的详细制作流程图,真实风格,适用于小红书图文比例",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/comparison_case55/output.jpg`,
    sourceTitle: "Chili Pork Cooking Flowchart",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-55-chili-pork-cooking-flowchart-by-kurt_rousey466",
    creator: "@Kurt_Rousey466",
  },
  {
    id: "creative-soft-poetic-childrens-book",
    category: "creative",
    title: "诗意儿童绘本插画",
    summary: "非常适合儿童书、温柔叙事和低饱和插画封面，负空间和纸感都很稳定。",
    prompt:
      "Soft poetic children's book illustration with watercolor and gouache textures.Clear gentle daylight with slightly brighter highlights.Muted pastel colors with soft blue and warm tones.Visible brush strokes and paper grain.Minimalist composition with large negative space.Calm, thoughtful, slightly open-ended atmosphere.\n\nChild character (around 12 years old).Subtle visual metaphors like light, shadow, perspective, reflection.Hand-painted picture book style, not cartoon, not anime, not 3D.\n\nTwo children in calm conversation,soft connection forming.",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/comparison_case61/output.jpg`,
    sourceTitle: "Soft Poetic Children's Book Illustration",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-61-soft-poetic-childrens-book-illustration-with-watercolor-and-gouache-textures-by-dotey",
    creator: "@dotey",
  },
  {
    id: "poster-racing-spec-sheet",
    category: "poster",
    title: "赛车参数海报",
    summary: "非常适合汽车、机甲、硬件这类带规格参数的海报，一句话就能起技术型主视觉。",
    prompt: "generate an image of a racing car poster with its spec and pricing",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case68/output.jpg`,
    sourceTitle: "Racing Spec Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-68-racing-spec-poster",
    creator: "@kevinmckenna",
  },
  {
    id: "poster-chaplin-product-redesign",
    category: "poster",
    title: "卓别林产品广告重设计",
    summary: "适合把现有商品图换成更有记忆点的人物广告图，偏简约干净的商业海报路线。",
    prompt: "重新生成一张海报，卓别林拿着商品图里的止痒膏，面露微笑。风格要简约干净。",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case69/output.jpg`,
    sourceTitle: "Product Ad Redesign",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-69-product-ad-redesign",
    creator: "@genel_ai",
  },
  {
    id: "creative-food-specimen-anatomy",
    category: "creative",
    title: "食物标本解剖图",
    summary: "适合做食物结构、器物剖面和高细节知识图，风格非常强，信息图味道也足。",
    prompt: `一颗/一块/一枚【食物名称】，以博物学大师发现野外标本的方式解剖。
剖开、展开、固定——如同博物馆的珍贵藏品，
却以卡拉瓦乔为《国家地理》掌镜时的光线照亮。
每一个内部结构都以自身的材质真相发光。
截面锋利得近乎暴力。内部美丽得近乎神圣。
画面中呈现完整标本：
一半保持原状，展示【外表面描述：质感/颜色/纹理】；
另一半剖开至核心，【内部核心结构描述：最重要的1—2个内部视觉特征】清晰可见。
【补充1—2句该食物最具视觉张力的横截面细节描述】
背景：纯粹的黑丝绒。
【食物名称】悬浮其中，如同某件珍贵而危险的事物。`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/comparison_case68/output.jpg`,
    sourceTitle: "Botanical Food Specimen Anatomy Chart",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-68-botanical-food-specimen-anatomy-chart",
    creator: "@alanlovelq",
  },
  {
    id: "creative-poster-to-trailer",
    category: "creative",
    title: "海报转预告片概念",
    summary: "适合把静态海报继续往动态叙事延展，做 trailer 概念帧和宣传片分镜灵感。",
    prompt: "「このポスターを見みて、自分で妄想してトレーラー映像を作ってくれ。」",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/comparison_case71/output.jpg`,
    sourceTitle: "Poster-to-Trailer Concept",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-71-poster-to-trailer-concept",
    creator: "@Shentoan",
  },
  {
    id: "poster-rubber-duck-live-action",
    category: "poster",
    title: "橡皮鸭男孩真人电影海报",
    summary: "适合童话冒险、IP 电影化和角色故事主视觉，偏暖调真人电影海报方向。",
    prompt:
      "可愛いラバーダックの男の子「ルヒア(RUHiA)」が日本を目指して大冒険をして日本人女性の「ミライ」と出会うまでの物語。それを実写映画のポスターのようにして。",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/comparison_case72/output.jpg`,
    sourceTitle: "Rubber Duck Boy Live-Action Movie Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-72-rubber-duck-boy-live-action-movie-poster",
    creator: "@kotobuki_umi",
  },
];
