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
export const IMAGE_PROMPT_GALLERY_UPSTREAM_JSON_URL =
  "https://raw.githubusercontent.com/EvoLinkAI/awesome-gpt-image-2-prompts/main/gpt_image2_prompts.json";

const IMAGE_PREVIEW_BASE_URL =
  "https://raw.githubusercontent.com/EvoLinkAI/awesome-gpt-image-2-prompts/main/images";

type UpstreamImagePromptMedia = {
  type?: string;
  url?: string;
};

type UpstreamImagePromptEntry = {
  id?: string;
  url?: string;
  author?: string;
  lang?: string;
  text?: string;
  media?: UpstreamImagePromptMedia[];
  likeCount?: number;
  viewCount?: number;
};

let imagePromptGalleryItemsPromise: Promise<ImagePromptGalleryItem[]> | null = null;

const IMAGE_PROMPT_GALLERY_AUTO_SUMMARY_PREFIX = "上游 JSON 自动同步：";
const IMAGE_PROMPT_GALLERY_EXCLUDED_TERMS = [
  "sexy",
  "cleavage",
  "lingerie",
  "underwear",
  "xxxx",
  "偷拍",
  "丝袜",
  "内衣",
  "口红直播间",
] as const;
const IMAGE_PROMPT_GALLERY_EXCLUDED_PATTERNS = [
  /prompt.*(?:reply|comment|below)/i,
  /prompt.*comments?/i,
  /prompt.*alt/i,
  /^\s*\(?c(?:h|he)a?e?ck?\s+in\s+comments?\)?\s*$/i,
  /^\s*\(?check\s+comments?\)?\s*$/i,
  /prompt见评论/i,
  /见评论/,
  /看评论/,
  /评论区/,
  /ツリー/,
  /reply below/i,
  /altに載せて/i,
  /プロンプト.*ツリー/i,
  /やり方とプロンプトはツリー/i,
] as const;
const IMAGE_PROMPT_GALLERY_RESOLVED_PROMPTS: Record<string, string> = {
  "https://x.com/ProperPrompter/status/2046534215311970694":
    "Create a 10 × 10 grid of 100 different fantasy RPG items rendered in classic pixel art style (16-bit or 32-bit sprite aesthetic, reminiscent of SNES/GBA-era JRPGs). Each item should appear in its own square tile with a short clear label underneath. Keep the grid neat on a white background. Make every item visually distinct and every label correctly spelled. Use crisp pixel edges, limited palette per sprite, and subtle dithering for shading. Use these row themes: Row 1: swords and blades Row 2: shields and armor Row 3: bows, crossbows, and ranged weapons Row 4: staves, wands, and magical foci Row 5: potions, elixirs, and flasks Row 6: scrolls, tomes, and spellbooks Row 7: rings, amulets, and enchanted trinkets Row 8: helmets, crowns, and headgear Row 9: keys, relics, and quest items Row 10: gems, runes, and crafting materials Show each tile as a centered item sprite on a clean background square, rendered as a classic inventory icon — the kind you'd see in a fantasy RPG menu. Keep the overall style consistent, cohesive, and reminiscent of beloved retro fantasy RPGs — charming, detailed, and instantly readable at small sizes.",
  "https://x.com/agi_aibusi/status/2046530758190440928": `GPT-image-2でこの手相を診断して詳細な鑑定書を作って
生命線・知能線・感情線・運命線・太陽線・財運線・結婚線を、線の形状・濃淡・枝分かれ・起点終点まで分析すること。
助言を重点的に高品質な占い鑑定書にまとめること。`,
  "https://x.com/minesan_ai/status/2046215187678790140":
    "添付の女の子に織田信長の生涯を解説する漫画を作成させて 9:16のFHDで、日本語のセリフで、日本のコミックスのページとコマの流れで作成してください。 絵柄はキャラクターに合わせてください。 全５ページで作成してください",
  "https://x.com/hiro_ai_auto/status/2046542225358917945":
    '{ "type": "UIデザインシステムのデモプロジェクト", "theme": "{argument name=\\"visual theme\\" default=\\"光学サイエンスと光の屈折\\"}", "overall_aesthetic": "クリーンな白背景、ライトモード、未来感、高級感、{argument name=\\"primary gradient colors\\" default=\\"虹彩、やわらかなオレンジ、イエロー、シアン、パープル、ピンク\\"} をアクセントにしたデザイン", "header": { "title": "{argument name=\\"system name\\" default=\\"LIGHTCORE PRISM\\"}", "subtitle": "UIデザインシステム - ライトモード", "tags": ["未来感", "高級感", "集中感"], "hero_graphic": "屈折した虹彩の光をまとった3D透明ガラスリング" }, "layout": { "sections": [ { "title": "カラー", "count": 5, "labels": ["ホワイト [#FFFFFF]", "スノー [#FAFAFC]", "スレート [#F2F4F8]", "ボーダー [#E6E8EF]", "ブラック [#0A0A0C]"], "description": "角丸の正方形カラーサンプルを5つ配置" }, { "title": "プリズムグラデーション", "count": 1, "description": "横長のグラデーションバーを1本配置し、その下に16進カラーコードを5つ表示" }, { "title": "タイポグラフィ", "description": "大きな『Aa』の見本、4種類のウェイト（Light, Regular, Medium, Semibold）、およびアルファベットと数字の一覧を表示" }, { "title": "アイコン", "count": 12, "description": "ミニマルなラインスタイルのアイコンを12個、2×6のグリッドで配置" }, { "title": "ボタン", "count": 8, "categories": ["プライマリ", "セカンダリ", "テキスト", "アイコン"], "description": "合計8個のボタンを配置し、各カテゴリごとに通常状態と無効状態を表示。プライマリボタンは虹彩のボーダーを持ち、テキストは {argument name=\\"primary button text\\" default=\\"使い始める\\"}" }, { "title": "ナビゲーション", "count": 2, "variants": ["デスクトップ", "モバイル"], "description": "デスクトップ版ナビゲーションにはロゴ、4つのテキストリンク、検索、ログイン、ボタンを含む。モバイル版ナビゲーションにはロゴ、検索、ハンバーガーメニューを含む" }, { "title": "コンポーネント", "count": 6, "items": ["カード：抽象的な虹彩グラフィックとボタン付きの『Photon Engine』カード", "入力欄：ラベル付き検索バーとメールアドレス入力欄", "プログレスバー：68%の虹彩プログレスバー", "タブ：概要、分析、設定", "スイッチ：2つのトグルスイッチ（オン/オフ）", "データ可視化：凡例3項目付きのドーナツチャート1つ、7日間の折れ線グラフ1つ"] }, { "title": "Webページ", "description": "デスクトップブラウザのモックアップ。見出しは \'{argument name=\\"hero headline\\" default=\\"光と色で未来をつくる\\"}\'、2つのボタン、流れるような3D虹彩ウェーブグラフィック、下部に5つのパートナーロゴを表示" }, { "title": "モバイルアプリ", "description": "スマートフォンのモックアップ。残高24,880ドル、折れ線グラフ、4つのクイックアクションアイコン、3件の最近のアクティビティ一覧、4つのアイコン付き下部ナビゲーションバーを表示" } ] } }',
};

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
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/case_case73/output.jpg`,
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
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case87/output.jpg`,
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
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case89/output.jpg`,
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
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case55/output.jpg`,
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
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case82/output.jpg`,
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
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case105/output.jpg`,
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
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/poster_case106/output.jpg`,
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
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/case_case112/output.jpg`,
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
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/case_case115/output.jpg`,
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
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/case_case116/output.jpg`,
    sourceTitle: "Rubber Duck Boy Live-Action Movie Poster",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-72-rubber-duck-boy-live-action-movie-poster",
    creator: "@kotobuki_umi",
  },
  {
    id: "character-galgame-profile-page",
    category: "character",
    title: "Galgame 角色介绍页",
    summary: "把立绘、Q 版和人物档案揉成游戏官网角色页，适合视觉小说、角色设定展示和官网风页面起稿。",
    prompt: `最新モデルの画像生成ツールを使用して、
このちびキャライラストと立ち絵を使って本物のサイトページのようにキャラクター紹介ページ風イラストを作ってください。 （紹介ページとして使ってもおかしくないもの）
ギャルゲーのキャラクター紹介ページをイメージした高品質なもの。 顔の差分なども乗っている、CGイラストが存在する。ちびキャラが存在する。

「ここに自己紹介」

名前:（ここに名前）
イメージカラー:（ここに色）
身長:（ここに身長）cm
体重:（ここに体重）kg
キャッチコピー:”「ここにセリフ」”`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/character_case3/output.jpg`,
    sourceTitle: "Gal Game Character Introduction Page",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-3-gal-game-character-introduction-page-by-09lyco",
    creator: "@09lyco",
  },
  {
    id: "character-mecha-sea-city-key-visual",
    category: "character",
    title: "海城机甲少女主视觉",
    summary: "适合世界观海报、机甲角色定妆和故事 key visual，角色、装备和环境氛围一次成型。",
    prompt:
      "A mecha girl mid-teens, pale skin smudged with soot and salt spray, sharp amber eyes with glowing HUD reticles, waist-length ash-white hair tied in a high ponytail whipping in the sea wind, matte gunmetal exoskeleton armor plating her shoulders, forearms and shins, exposed hydraulic pistons at the joints, chest rig with glowing cyan coolant lines, oversized oil-stained hangar jacket half slipping off one shoulder, a massive rail cannon resting on her right shoulder, dog tags and frayed red ribbon at her collar, standing off-center to the left on the rusted edge of a tilted steel platform jutting out over dark water, weight shifted onto one leg, left hand gripping the cannon strap, head turned slightly toward camera with a quiet defiant stare, steam venting from her back thrusters, her ponytail and jacket streaming sideways in the salt wind, a vast derelict sea-city at dusk, colossal megastructures of unknown purpose rising from the ocean in staggered silhouettes, bone-white monolithic towers fused with barnacled steel, cyclopean ring-shaped constructs canted at broken angles, rusted skeletal gantries threaded with dead cables, dark swells rolling between the pylons, shipwrecks half-swallowed at their feet, thick sea fog clinging to the bases while the upper structures pierce into a bruised sky, scattered faint lights blinking high in the towers like distant eyes, moody low-key lighting, cold teal ambient from the overcast sky, warm amber sodium glow leaking from a distant structure camera-right, hard backlight from a low sun behind the towers carving her silhouette, volumetric god rays cutting through sea mist, wet specular highlights on her armor, 35mm anamorphic lens, slight low angle looking up past her shoulder toward the structures, medium-wide shot, shallow depth of field with foreground rust in soft focus, horizontal lens flares, fine atmospheric haze compressing the distant megastructures into layered silhouettes, cinematic anime key visual, painterly digital illustration with crisp line art, desaturated oceanic palette of teal, bone-white and rust punched by small warm accent lights, film grain, high-contrast editorial poster aesthetic. Format 16:9.",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/character_case7/output.jpg`,
    sourceTitle: "Mecha Girl Sea-City Key Visual",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-7-mecha-girl-sea-city-key-visual-by-old_pgmrs_will",
    creator: "@old_pgmrs_will",
  },
  {
    id: "ui-song-dynasty-social-feed",
    category: "ui",
    title: "宋朝朋友圈界面",
    summary: "古今穿越的社交 feed 模板，适合历史戏仿、知识传播和叙事型 UI 概念图。",
    prompt:
      '"宋朝人的朋友圈"/"SONG DYNASTY SOCIAL MEDIA FEED"，古今穿越幽默融合界面设计风格，画面模拟手机社交媒体界面，但内容全部是宋朝场景头像是宋代文人画像，用户名"苏东坡SuShi_Official"，发布内容"刚到黄州，被贬了但心情还行。今天自己做了东坡肉，味道绝了，附菜谱："，配图为工笔画风格的东坡肉特写，点赞列表"黄庭坚、秦观、佛印等126人"，评论区"王安石：呵呵""司马光：还是那个味道"，界面元素如点赞图标用宋代花纹替代，状态栏显示"大宋移动 5G"和"元丰三年"，配色为手机深色模式搭配宋代雅致色调，历史与社交媒体的趣味碰撞杰作',
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case4/output.jpg`,
    sourceTitle: "Song Dynasty Social Media Feed",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-4-song-dynasty-social-media-feed-by-panda20230902",
    creator: "@Panda20230902",
  },
  {
    id: "ui-style-reference-system",
    category: "ui",
    title: "参考风格扩展 UI 系统",
    summary: "把一张参考视觉扩成整套网页与移动端设计语言，适合从 moodboard 快速落成 UI 草图。",
    prompt:
      "用这种风格帮我生成一套UI设计系统，包含网页、移动端、卡片、控件、按钮以及其它。把这套视觉风格作为参考生成网页。我尝试了宇宙、飞行、蝴蝶主题。",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case9/output.jpg`,
    sourceTitle: "Style-to-UI Design System",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-9-style-to-ui-design-system-by-stark_nico99",
    creator: "@stark_nico99",
  },
  {
    id: "ui-hanfu-museum-breakdown",
    category: "ui",
    title: "博物馆式汉服拆解图",
    summary: "适合服饰、器物和文博主题的中文拆解信息图，结构、材质和文化说明都很完整。",
    prompt: `请根据【主题】自动生成一张“博物馆图鉴式中文拆解信息图”。

要求整张图兼具真实写实主视觉、结构拆解、中文标注、材质说明、纹样寓意、色彩含义和核心特征总结。你需要根据【主题】自动判断最合适的主体对象、服饰体系、器物结构、时代风格、关键部件、材质工艺、颜色方案与版式结构，用户无需再提供其他信息。

整体风格应为：国家博物馆展板、历史服饰图鉴、文博专题信息图，而不是普通海报、古风写真、电商详情页或动漫插画。背景采用米白、绢纸白、浅茶色等纸张质感，整体高级、克制、专业、可收藏。

版式固定为：
- 顶部：中文主标题 + 副标题 + 导语
- 左侧：结构拆解区，中文引线标注关键部件，并配局部特写
- 右上：材质 / 工艺 / 质感区，展示真实纹理小样并附说明
- 右中：纹样 / 色彩 / 寓意区，展示主色板、纹样样本和文化解释
- 底部：穿着顺序 / 构成流程图 + 核心特征总结

若主题适合人物展示，则以真实人物全身站姿为中央主体；若更适合器物或单体结构，则改为中心主体拆解图，但整体仍保持完整中文信息图形式。所有文字必须为简体中文，清晰、规整、可读，不要乱码、错字、英文或拼音。重点突出真实结构、材质差异、文化说明与图鉴气质。

避免：海报感、影楼感、电商感、动漫感、cosplay感、乱标注、错结构、糊字、假材质、过度装饰。`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/ui_case25/output.jpg`,
    sourceTitle: "Museum-Style Hanfu Breakdown Infographic",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-25-museum-style-hanfu-breakdown-infographic-by-mrlarus",
    creator: "@MrLarus",
  },
  {
    id: "poster-vintage-newspaper-frontpage",
    category: "poster",
    title: "复古报纸头版设计",
    summary: "适合人物专题、剧情海报和品牌故事页，能把一张图直接包装成老报纸头版。",
    prompt: `Create the most realistic front page design of a vintage newspaper featuring the main character. The layout should be made in the style of a real printed newspaper with a cinematic black-and-white aesthetic.
The main photo should be prominently placed in the center, framed, like the image in the title of the article. The subject in the photo should remain unchanged and clearly distinguishable in natural light and slightly increased contrast in order to match the spectacular editorial style.
Create a bold, attention-grabbing headline at the top (create a unique title that matches the spirit of the photo - it can be romantic, mysterious, funny, or dramatic). Add a smaller subtitle under it, which will look like a real newspaper caption.
Add realistic newspaper elements:
Columns of small text (in the style of lorem ipsum, but framed like real news)
At the top is the fictitious name of the publication (for example, The Daily Prompts, AI Times or similar - think creatively, according to the picture)
Date, issue number and location
Decorative lines, dividers, and vintage typography
Small additional articles or captions to the main image
Optional stamps, doodles, or editorial notes to add personality.
Style:
Black and white or slightly faded monochrome paper
Fine paper texture, grain, and ink defects
Small shadows and creases that mimic real printed paper
The aesthetics of a clean but slightly worn vintage newspaper
Mood: Give the design personality, expressiveness and plot, as if the plot is part of the main article.
Aspect ratio: 4:5 or 1:1
High-detail, ultra-realistic hybrid of editorial photography and print design.`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/portrait_case70/output.jpg`,
    sourceTitle: "Vintage Newspaper Front Page Design",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-19-create-the-most-realistic-front-page-design-of-a-vintage-newspaper-featuring-by-naiknelofar788",
    creator: "@Naiknelofar788",
  },
  {
    id: "poster-travel-magazine-feature",
    category: "poster",
    title: "旅游杂志专题文章",
    summary: "适合做信息密度高的城市攻略页、旅行专题和 photo-book 风杂志排版。",
    prompt:
      "Create image of Magazine feature article [travel] guide page, cute, information dense photo book style magazine feature article page. Add all necessary sections, tips, recommendations, information. add photos for any sections and recommendations if you like. Place the attached person at the precise location of [city, country]. Seamlessly blend the attached person as if they are sightseeing. Approach this task with the understanding that this is a critical, information rich page that will significantly influence visitor numbers, text accuracy is important. Fully use the entire [9:16] page. NEGATIVE PROMPT: coordinate texts @swiat_ai @ProfitAII",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/portrait_case71/output.jpg`,
    sourceTitle: "Magazine Travel Guide Feature Article",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-20-create-image-of-magazine-feature-article-travel-by-andis13",
    creator: "@andis13",
  },
  {
    id: "creative-json-prompt-reconstruction",
    category: "creative",
    title: "照片分析与 JSON Prompt 重建",
    summary: "适合做逆向提示词、统一色彩风格和稳定 UGC 角色参考，偏方法论型灵感。",
    prompt: `analyze this photo and give me a detailed JSON prompt that recreates it. break down the color grading and every exact color in the photo

(use Opus, not Sonnet. Opus has stronger visual analysis and writes more detailed JSON)

paste that JSON into ChatGPT
upload your product image and prompt:
using this JSON as reference, generate a person holding my product
save that generated photo as your character reference

attach it to every future generation for facial consistency

you now have a consistent UGC model that works across any product

the JSON controls the lighting and color grading. GPT image-2 handles the character. you control the product placement.

the #1 tell on AI photos is flat colors and a grainy look. this method removes both.
5 minutes to set up. unlimited variations after.`,
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/portrait_case77/output.jpg`,
    sourceTitle: "Photo Analysis & JSON Prompt Reconstruction",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-21-analyze-this-photo-and-give-me-a-detailed-json-prompt-that-recreates-it-brea-by-pavellaslov",
    creator: "@pavellaslov",
  },
  {
    id: "creative-green-tea-product-kit",
    category: "creative",
    title: "绿茶胶片套装产品摄影",
    summary: "适合护肤、包装和生活方式产品的品牌静物图，适配轻高端、自然系商业视觉。",
    prompt:
      "CALMING GREEN TEA Film Kit displayed frontally, the open box shows soft sage-green film pouches and translucent ampoules with matte silver caps, product placed centrally with clear branding CALMING GREEN TEA -- 7 Days to Soothed Skin, pastel green background with botanical graphic accents, three minimal icons (leaf, wave, balance) floating around the product to emphasize benefits, photographic, hyper detailed, ultra realistic, lifelike, 8k, high detail, soft professional lighting.",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/portrait_case78/output.jpg`,
    sourceTitle: "Green Tea Film Kit Product Photography",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-22-calming-green-tea-film-kit-displayed-frontally-the-open-box-shows-soft-sage-by-zarairahh",
    creator: "@ZaraIrahh",
  },
  {
    id: "ui-laptop-saas-mockup",
    category: "ui",
    title: "笔记本上的超写实 UI 模型",
    summary: "适合 SaaS 官网、设计作品集和产品展示页，一句 prompt 就能起高质感设备 mockup。",
    prompt:
      "A hyper-realistic UI/UX mockup displayed on a slim modern laptop placed on a minimal wooden desk with soft natural daylight. The screen shows a clean SaaS dashboard with elegant typography, glassmorphism cards, smooth gradients, subtle drop shadows, and neatly spaced components. Visible charts, analytics panels, sidebar navigation, and micro-interactions. Realistic macOS-style window frame, soft reflections on the screen, shallow depth of field, cozy workspace atmosphere, shot in photorealistic product photography style, ultra-detailed.",
    previewImageUrl: `${IMAGE_PREVIEW_BASE_URL}/portrait_case80/output.jpg`,
    sourceTitle: "Hyper-Realistic Laptop UI Mockup",
    sourceUrl:
      "https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts/blob/main/README_zh-CN.md#case-24-a-hyper-realistic-uiux-mockup-displayed-on-a-slim-modern-laptop-placed-on-a-by-zarairahh",
    creator: "@ZaraIrahh",
  },
  {
    id: "ui-elon-douyin-livestream",
    category: "ui",
    title: "Elon Musk 抖音直播截图",
    summary: "适合直播间 UI、礼物特效和中文评论区截图风格，直接参考短视频平台的完整界面结构。",
    prompt: `A 9:16 vertical version, high-detail realistic style Chinese TikTok live screenshot, Elon Musk is talking to the mobile phone camera in the live broadcast room, excited, smiling, and the live atmosphere is warm and real. He held a white handwritten sign in one hand, which clearly said: "Thank you Shinning". There are obvious Chinese TikTok interface elements in the live broadcast screen, including likes, comments and share icons arranged vertically on the right, scrolling Chinese bullet screens and interactive comments below, and the "live broadcast" logo at the top, which looks like a real mobile phone screenshot. There is an eye-catching gift prompt special effect in the screen: "Shinning sent TikTok No. 1", with gift animation light effect and platform-style prompt box. Musk is in a professional live broadcast environment, with a mobile phone holder, a ring fill light and a desktop microphone in front of him. The background is a modern technology live broadcast room with bright lights and a slight neon atmosphere. The composition is real and natural, like the ongoing live screenshot of the Chinese short video platform. The interface information is rich but not messy, the characters are clear, the expression is vivid, the details are rich, the sense of real photography, the depth of field, high definition, cinematic, photorealistic, realistic livestream screenshot, social media UI, Chinese Douyin live room, detailed lighting, natural skin texture.

Negative prompts:

Low definition, blur, cartoon, illustration, too strong CG sense, two-dimensional, deformed fingers, wrong text, scrambled code, multiple mobile phones, multiple brands, character repetition, face collapse, facial features distortion, excessive skin polishing, overexposure, too dark, messy background, wrong UI, non-Chinese short video interface, too many English bullet screens, gift special effects are not obvious, cropping error, proportional error

Supplementary reinforcement words:

Real mobile phone screen recording screenshot feeling, the live broadcast UI is complete, the gift prompt box conforms to the style of the Chinese short video platform, the Chinese comment area is active, the number of people online in the live broadcast room is clearly displayed, and the time, power and signal bar are visible.`,
    previewImageUrl: "https://pbs.twimg.com/media/HGaiU_8XoAAAkaS.jpg",
    sourceTitle: "Elon Musk Chinese TikTok Live Screenshot",
    sourceUrl: "https://x.com/Shinning1010/status/2046501587762188535",
    creator: "@Shinning1010",
  },
  {
    id: "ui-cixi-x-homepage",
    category: "ui",
    title: "慈禧 X 主页",
    summary: "适合历史人物社交主页、戏仿式个人页和平台界面概念，短 prompt 但场景辨识度很强。",
    prompt: "生成一张慈禧的X主页",
    previewImageUrl: "https://pbs.twimg.com/media/HGVw2JUbQAAG9Bn.jpg",
    sourceTitle: "Empress Dowager Cixi X Page",
    sourceUrl: "https://x.com/Cryptohaifeng_/status/2046165776055546341",
    creator: "@Cryptohaifeng_",
  },
  {
    id: "poster-japanese-supermarket-flyer",
    category: "poster",
    title: "日式超市特卖传单",
    summary: "适合折页广告、促销 flyer 和高密度商品排版，尤其适合零售和本地商超视觉方向。",
    prompt:
      "『賑やかで魅力的なスーパーマーケットの折り込みチラシの画像。上部には「特売」の大きな文字と今週の日付。カラフルな商品写真（野菜・果物・牛肉・鮮魚）、赤枠の価格タグ、「超目玉商品」「家計応援」のキャッチ…』",
    previewImageUrl: "https://pbs.twimg.com/media/HGatbcobIAAuNfa.jpg",
    sourceTitle: "Japanese Supermarket Sale Flyer",
    sourceUrl: "https://x.com/weel_corp/status/2046514558064586782",
    creator: "@weel_corp",
  },
  {
    id: "creative-backpropagation-diagram",
    category: "creative",
    title: "反向传播图解",
    summary: "适合知识图、教程图和课程配图，把抽象概念直接做成结构清晰的教学信息图。",
    prompt: "バックプロパゲーションについて詳しく図解して",
    previewImageUrl: "https://pbs.twimg.com/media/HGabrymaUAAoDXS.jpg",
    sourceTitle: "Backpropagation Explained Diagram",
    sourceUrl: "https://x.com/itnavi2022/status/2046494262158930154",
    creator: "@itnavi2022",
  },
  {
    id: "creative-programming-museum-cartoon",
    category: "creative",
    title: "编程博物馆现场表演",
    summary: "适合技术梗图、程序员文化海报和轻讽刺卡通场景，做社区传播图会很有辨识度。",
    prompt:
      "在计算机博物馆里，一个程序员在展厅中央，正在演示C语言编程，很多参观者在围观，屏幕上的代码清晰可见。旁边的牌子写着：古法编程，现场表演。2D卡通画风，16:9",
    previewImageUrl: "https://pbs.twimg.com/media/HGaumsnbYAAxaPl.jpg",
    sourceTitle: "Retro Programming Museum Cartoon",
    sourceUrl: "https://x.com/XiaohuiAI666/status/2046515319947354603",
    creator: "@XiaohuiAI666",
  },
  {
    id: "character-gold-saints-card-grid",
    category: "character",
    title: "黄金圣斗士卡牌九宫格",
    summary: "适合角色卡组、阵营卡面和多人物集合页，能快速起 12 宫格式角色展示版面。",
    prompt: "生成圣斗士星矢12个黄金圣斗士的12宫格卡牌图片，每张卡牌上写上对应的中文名，每行4个，宽高比16:9。",
    previewImageUrl: "https://pbs.twimg.com/media/HGaLQTfbkAA3xpN.jpg",
    sourceTitle: "Saint Seiya Gold Saints Card Grid",
    sourceUrl: "https://x.com/songguoxiansen/status/2046476566537080849",
    creator: "@songguoxiansen",
  },
  {
    id: "poster-science-fiction-movie",
    category: "poster",
    title: "科幻电影海报",
    summary: "非常适合快速起电影主视觉方向，留给后续世界观、标题和角色设定继续细化。",
    prompt: "Create a Science fiction movie poster",
    previewImageUrl: "https://pbs.twimg.com/media/HGatt-VasAAVQq2.jpg",
    sourceTitle: "Science Fiction Movie Poster",
    sourceUrl: "https://x.com/underwoodxie96/status/2046514205529088501",
    creator: "@underwoodxie96",
  },
  {
    id: "ui-palm-reading-report",
    category: "ui",
    title: "手相鉴定报告单",
    summary: "适合诊断书、报告页和分析卡片类界面，把复杂文本信息整理成一张可读结果页。",
    prompt: `GPT-image-2でこの手相を診断して詳細な鑑定書を作って
生命線・知能線・感情線・運命線・太陽線・財運線・結婚線を、線の形状・濃淡・枝分かれ・起点終点まで分析すること。
助言を重点的に高品質な占い鑑定書にまとめること。`,
    previewImageUrl: "https://pbs.twimg.com/media/HGa8bFSbsAA6rpa.jpg",
    sourceTitle: "Palm Reading Diagnosis Report",
    sourceUrl: "https://x.com/agi_aibusi/status/2046530764871696750",
    creator: "@agi_aibusi",
  },
  {
    id: "creative-handwritten-prescription",
    category: "creative",
    title: "手写中西医药方图",
    summary: "适合做拟真单据、手写文档和处方笺类图片，文档生成方向会很有参考价值。",
    prompt: "生成一张手写中/西医药方图",
    previewImageUrl: "https://pbs.twimg.com/media/HGaqaO2W4AA2W-6.jpg",
    sourceTitle: "Handwritten Prescription Sheet",
    sourceUrl: "https://x.com/MrLarus/status/2046514998965371144",
    creator: "@MrLarus",
  },
  {
    id: "poster-ten-fake-service-ads",
    category: "poster",
    title: "十组虚构服务广告",
    summary: "适合做 campaign brainstorming、服务定位海报和批量广告创意探索，一次就能起多张方向图。",
    prompt: "在りそうでないサービスの広告を10サービズ(1サービス1枚)作成して下さい",
    previewImageUrl: "https://pbs.twimg.com/amplify_video_thumb/2046386914522255361/img/wG4VXG8ZhIRqaY84.jpg",
    sourceTitle: "Ten Fictional Service Ads",
    sourceUrl: "https://x.com/Yuupapa_free/status/2046388238982771123",
    creator: "@Yuupapa_free",
  },
  {
    id: "creative-demenigis-encyclopedia",
    category: "creative",
    title: "桶眼鱼结构图鉴页",
    summary: "适合做生物结构图、百科页和科普卡，直接把某个对象组织成图鉴式知识页面。",
    prompt: "デメニギスの体の構造を解説するカラー図鑑のページ",
    previewImageUrl: "https://pbs.twimg.com/media/HGahSugbEAA0yOv.jpg",
    sourceTitle: "Barreleye Fish Anatomy Encyclopedia Page",
    sourceUrl: "https://x.com/itnavi2022/status/2046500429786402973",
    creator: "@itnavi2022",
  },
  {
    id: "ui-trump-kim-douyin-pk",
    category: "ui",
    title: "特朗普与金正恩抖音 PK 直播",
    summary: "适合双人直播、PK 页面和强互动评论区截图，偏平台戏仿与事件感界面方向。",
    prompt: "生成特朗普和金正恩在抖音直播间打PK的截图",
    previewImageUrl: "https://pbs.twimg.com/media/HGUGld9bAAAUe_s.jpg",
    sourceTitle: "Trump and Kim Douyin PK Screenshot",
    sourceUrl: "https://x.com/alanlovelq/status/2046048929490612464",
    creator: "@alanlovelq",
  },
  {
    id: "creative-chushibiao-blackboard",
    category: "creative",
    title: "黑板粉笔版出师表",
    summary: "适合教室板书、手写海报和拟真粉笔字场景，文字密集型生成会很有参考意义。",
    prompt: "生成图片: 手写在教室黑板上的出师表全文，真实感的粉笔字迹，晴朗白天用iPhone手机实拍",
    previewImageUrl: "https://pbs.twimg.com/media/HGUGld9bAAAUe_s.jpg",
    sourceTitle: "Classroom Blackboard Full-Text Calligraphy",
    sourceUrl: "https://x.com/alanlovelq/status/2046048929490612464",
    creator: "@alanlovelq",
  },
  {
    id: "ui-t800-taobao-detail-page",
    category: "ui",
    title: "T-800 淘宝商品详情页",
    summary: "适合商品详情页、三视图参数页和电商介绍长图，信息结构很完整。",
    prompt: "生成图片: T-800机器人的淘宝商品详情页，展示: 机器人的正面侧面背面三视图， 产品价格， 产品细节， 功能和使用场景等",
    previewImageUrl: "https://pbs.twimg.com/media/HGUGld9bAAAUe_s.jpg",
    sourceTitle: "T-800 Taobao Product Detail Page",
    sourceUrl: "https://x.com/alanlovelq/status/2046048929490612464",
    creator: "@alanlovelq",
  },
  {
    id: "creative-prewar-lab-minecraft",
    category: "creative",
    title: "战前日本研究所 Minecraft 截图",
    summary: "适合世界观场景图、像素风叙事和游戏截图式概念图，氛围感很强。",
    prompt: "戦前日本の怪しげな研究所を探検しているマイクラのスクリーンショット画像を作成して",
    previewImageUrl: "https://pbs.twimg.com/media/HGZLYdWaMAAQScz.jpg",
    sourceTitle: "Pre-war Japan Lab Minecraft Screenshot",
    sourceUrl: "https://x.com/RitaStar1128/status/2046406024303976904",
    creator: "@RitaStar1128",
  },
  {
    id: "creative-counter-strike-terraria-mashup",
    category: "creative",
    title: "反恐精英 × Terraria 截图混搭",
    summary: "适合游戏 crossover、风格混合实验和 meme 式截图创作，作为创意参考很有意思。",
    prompt: "counter strike in game screenshot, mixed with Terraria",
    previewImageUrl: "https://pbs.twimg.com/media/HGZPY4FbAAAljq3.jpg",
    sourceTitle: "Counter-Strike x Terraria Screenshot Mashup",
    sourceUrl: "https://x.com/yssrski/status/2046410519595348397",
    creator: "@yssrski",
  },
];

export function normalizeImagePromptGalleryPrompt(value: string) {
  return String(value || "")
    .trim()
    .replace(/\r\n/g, "\n")
    .replace(/\s+/g, " ")
    .replace(/^[`"'“”‘’]+|[`"'“”‘’]+$/g, "");
}

export async function loadImagePromptGalleryItems(): Promise<ImagePromptGalleryItem[]> {
  if (imagePromptGalleryItemsPromise) {
    return imagePromptGalleryItemsPromise;
  }

  imagePromptGalleryItemsPromise = fetch(IMAGE_PROMPT_GALLERY_UPSTREAM_JSON_URL)
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`failed to load upstream prompt json: ${response.status}`);
      }
      const payload = (await response.json()) as unknown;
      if (!Array.isArray(payload)) {
        return [...IMAGE_PROMPT_GALLERY_ITEMS];
      }
      return buildImagePromptGalleryItems(payload);
    })
    .catch(() => [...IMAGE_PROMPT_GALLERY_ITEMS]);

  return imagePromptGalleryItemsPromise;
}

function buildImagePromptGalleryItems(entries: UpstreamImagePromptEntry[]) {
  const baseItems = buildCuratedImagePromptGalleryItems(entries);
  const upstreamItems = buildAutoImagePromptGalleryItems(entries, baseItems);
  return [...baseItems, ...upstreamItems];
}

function buildCuratedImagePromptGalleryItems(entries: UpstreamImagePromptEntry[]) {
  const previewOverrides = buildImagePromptGalleryPreviewOverrides(entries);
  return IMAGE_PROMPT_GALLERY_ITEMS.map((item) => ({
    ...item,
    previewImageUrl: previewOverrides[item.id] || item.previewImageUrl,
  }));
}

function buildImagePromptGalleryPreviewOverrides(entries: UpstreamImagePromptEntry[]) {
  const overrides: Record<string, string> = {};

  for (const item of IMAGE_PROMPT_GALLERY_ITEMS) {
    const match = findBestUpstreamPreviewMatch(item, entries);
    if (match) {
      overrides[item.id] = match;
    }
  }

  return overrides;
}

function buildAutoImagePromptGalleryItems(
  entries: UpstreamImagePromptEntry[],
  baseItems: ReadonlyArray<ImagePromptGalleryItem>,
) {
  const items: ImagePromptGalleryItem[] = [];

  for (const entry of entries) {
    const prompt = resolveUpstreamImagePrompt(entry);
    const sourceUrl = normalizeImagePromptGalleryUrl(String(entry.url || ""));
    const previewImageUrl = getUpstreamPreviewImageUrl(entry.media);
    if (!prompt || !sourceUrl || !previewImageUrl || !shouldIncludeUpstreamImagePrompt(prompt, entry)) {
      continue;
    }
    if (hasExistingImagePromptGalleryMatch(entry, baseItems) || hasExistingImagePromptGalleryMatch(entry, items)) {
      continue;
    }

    items.push({
      id: createAutoImagePromptGalleryId(entry, items.length),
      category: inferImagePromptGalleryCategory(prompt),
      title: createAutoImagePromptGalleryTitle(prompt),
      summary: createAutoImagePromptGallerySummary(prompt),
      prompt,
      previewImageUrl,
      sourceTitle: "Upstream JSON",
      sourceUrl,
      creator: formatImagePromptGalleryCreator(entry.author || ""),
    });
  }

  return items;
}

function shouldIncludeUpstreamImagePrompt(prompt: string) {
  const value = prompt.toLowerCase();
  if (IMAGE_PROMPT_GALLERY_EXCLUDED_TERMS.some((term) => value.includes(term))) {
    return false;
  }
  return !IMAGE_PROMPT_GALLERY_EXCLUDED_PATTERNS.some((pattern) => pattern.test(prompt));
}

function createAutoImagePromptGalleryId(entry: UpstreamImagePromptEntry, index: number) {
  const raw =
    String(entry.id || "").trim() ||
    normalizeImagePromptGalleryPrompt(String(entry.url || "")).replace(/[^a-zA-Z0-9]+/g, "-") ||
    `entry-${index}`;
  return `upstream-${raw.replace(/^-+|-+$/g, "") || `entry-${index}`}`;
}

function createAutoImagePromptGalleryTitle(prompt: string) {
  const firstLine =
    prompt
      .split("\n")
      .map((line) => line.trim())
      .find(Boolean) || "上游灵感";
  const cleaned = firstLine
    .replace(/^[\d\s、.:-]+/, "")
    .replace(/^[`"'“”‘’]+|[`"'“”‘’]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (!cleaned) {
    return "上游灵感";
  }
  const sentence = cleaned.split(/[。.!?！？]/)[0]?.trim();
  if (sentence && sentence.length <= 28) {
    return sentence;
  }
  if (cleaned.length <= 28) {
    return cleaned;
  }
  return `${cleaned.slice(0, 24).trim()}…`;
}

function createAutoImagePromptGallerySummary(prompt: string) {
  const firstMeaningfulLine =
    prompt
      .split("\n")
      .map((line) => line.trim())
      .find(Boolean) || "";
  const compactLine = firstMeaningfulLine.replace(/\s+/g, " ").trim();
  if (!compactLine) {
    return `${IMAGE_PROMPT_GALLERY_AUTO_SUMMARY_PREFIX}来自上游最新案例。`;
  }
  const excerpt = compactLine.length > 42 ? `${compactLine.slice(0, 42).trim()}…` : compactLine;
  return `${IMAGE_PROMPT_GALLERY_AUTO_SUMMARY_PREFIX}${excerpt}`;
}

function inferImagePromptGalleryCategory(prompt: string): ImagePromptGalleryCategory {
  const value = prompt.toLowerCase();

  if (
    [
      "ui",
      "dashboard",
      "landing page",
      "x page",
      "homepage",
      "social media",
      "screenshot",
      "live",
      "livestream",
      "douyin",
      "tiktok",
      "小红书",
      "淘宝",
      "taobao",
      "detail page",
      "slide",
      "report",
      "鉴定书",
      "截图",
      "主页",
      "直播",
    ].some((keyword) => value.includes(keyword))
  ) {
    return "ui";
  }

  if (
    [
      "character",
      "card",
      "角色",
      "卡牌",
      "三视图",
      "gal game",
      "mecha",
      "saint",
      "hero",
      "gold saints",
    ].some((keyword) => value.includes(keyword))
  ) {
    return "character";
  }

  if (
    [
      "poster",
      "海报",
      "ad",
      "advert",
      "campaign",
      "flyer",
      "cover",
      "movie",
      "magazine",
      "newspaper",
      "stamp",
      "travel guide",
      "promo",
      "特卖",
      "传单",
    ].some((keyword) => value.includes(keyword))
  ) {
    return "poster";
  }

  if (
    [
      "portrait",
      "photo",
      "photography",
      "selfie",
      "snapshot",
      "35mm",
      "dslr",
      "肖像",
      "写真",
      "人像",
      "coser",
      "cosplayer",
    ].some((keyword) => value.includes(keyword))
  ) {
    return "portrait";
  }

  return "creative";
}

function formatImagePromptGalleryCreator(value: string) {
  const normalized = String(value || "").trim().replace(/^@/, "");
  return normalized ? `@${normalized}` : "@upstream";
}

function hasExistingImagePromptGalleryMatch(
  entry: UpstreamImagePromptEntry,
  items: ReadonlyArray<ImagePromptGalleryItem>,
) {
  const prompt = resolveUpstreamImagePrompt(entry);
  const sourceUrl = normalizeImagePromptGalleryUrl(String(entry.url || ""));
  const creator = normalizeImagePromptGalleryCreator(String(entry.author || ""));
  if (!prompt) {
    return false;
  }

  for (const item of items) {
    const itemSourceUrl = normalizeImagePromptGalleryUrl(item.sourceUrl);
    if (sourceUrl && itemSourceUrl && sourceUrl === itemSourceUrl) {
      return true;
    }

    const itemPrompt = normalizeImagePromptGalleryPrompt(item.prompt);
    if (!itemPrompt) {
      continue;
    }

    const authorMatched = creator && creator === normalizeImagePromptGalleryCreator(item.creator);
    if (scoreImagePromptMatch(prompt, itemPrompt, authorMatched) >= 0.82) {
      return true;
    }
  }

  return false;
}

function resolveUpstreamImagePrompt(entry: UpstreamImagePromptEntry) {
  const sourceUrl = normalizeImagePromptGalleryUrl(String(entry.url || ""));
  const resolvedPrompt = sourceUrl ? IMAGE_PROMPT_GALLERY_RESOLVED_PROMPTS[sourceUrl] : "";
  const rawPrompt = normalizeImagePromptGalleryPrompt(String(entry.text || ""));
  return normalizeImagePromptGalleryPrompt(resolvedPrompt || rawPrompt);
}

function findBestUpstreamPreviewMatch(item: ImagePromptGalleryItem, entries: UpstreamImagePromptEntry[]) {
  const prompt = normalizeImagePromptGalleryPrompt(item.prompt);
  const sourceUrl = normalizeImagePromptGalleryUrl(item.sourceUrl);
  const creator = normalizeImagePromptGalleryCreator(item.creator);
  if (!prompt) {
    return "";
  }

  let bestScore = 0;
  let bestMediaUrl = "";

  for (const entry of entries) {
    const mediaUrl = getUpstreamPreviewImageUrl(entry.media);
    if (!mediaUrl) {
      continue;
    }

    const entryUrl = normalizeImagePromptGalleryUrl(entry.url);
    if (sourceUrl && entryUrl && sourceUrl === entryUrl) {
      return mediaUrl;
    }

    const entryPrompt = normalizeImagePromptGalleryPrompt(String(entry.text || ""));
    if (!entryPrompt) {
      continue;
    }

    const authorMatched = creator && creator === normalizeImagePromptGalleryCreator(entry.author || "");
    const score = scoreImagePromptMatch(prompt, entryPrompt, authorMatched);
    if (score > bestScore) {
      bestScore = score;
      bestMediaUrl = mediaUrl;
    }
  }

  if (bestScore < 0.82) {
    return "";
  }
  return bestMediaUrl;
}

function getUpstreamPreviewImageUrl(media: UpstreamImagePromptMedia[] | undefined) {
  if (!Array.isArray(media)) {
    return "";
  }
  for (const item of media) {
    const url = String(item?.url || "").trim();
    if (url && String(item?.type || "").trim().toLowerCase() === "photo") {
      return url;
    }
  }
  for (const item of media) {
    const url = String(item?.url || "").trim();
    if (url) {
      return url;
    }
  }
  return "";
}

function scoreImagePromptMatch(prompt: string, entryPrompt: string, authorMatched: boolean) {
  if (prompt === entryPrompt) {
    return 1 + (authorMatched ? 0.05 : 0);
  }

  const shorterLength = Math.min(prompt.length, entryPrompt.length);
  if (shorterLength >= 24 && (prompt.includes(entryPrompt) || entryPrompt.includes(prompt))) {
    return 0.97 + (authorMatched ? 0.03 : 0);
  }

  const commonPrefixLength = getCommonPrefixLength(prompt, entryPrompt);
  if (commonPrefixLength >= 48) {
    return 0.9 + Math.min(commonPrefixLength / 1000, 0.05) + (authorMatched ? 0.03 : 0);
  }

  const diceScore = calculateDiceCoefficient(prompt, entryPrompt);
  return diceScore + (authorMatched ? 0.05 : 0);
}

function calculateDiceCoefficient(left: string, right: string) {
  if (!left || !right) {
    return 0;
  }
  if (left === right) {
    return 1;
  }
  if (left.length < 2 || right.length < 2) {
    return 0;
  }

  const leftBigrams = buildBigrams(left);
  const rightBigrams = buildBigrams(right);
  if (leftBigrams.length === 0 || rightBigrams.length === 0) {
    return 0;
  }

  const counts = new Map<string, number>();
  for (const bigram of leftBigrams) {
    counts.set(bigram, (counts.get(bigram) || 0) + 1);
  }

  let overlap = 0;
  for (const bigram of rightBigrams) {
    const current = counts.get(bigram) || 0;
    if (current > 0) {
      overlap += 1;
      counts.set(bigram, current - 1);
    }
  }

  return (2 * overlap) / (leftBigrams.length + rightBigrams.length);
}

function buildBigrams(value: string) {
  const bigrams: string[] = [];
  for (let index = 0; index < value.length - 1; index += 1) {
    bigrams.push(value.slice(index, index + 2));
  }
  return bigrams;
}

function getCommonPrefixLength(left: string, right: string) {
  const maxLength = Math.min(left.length, right.length);
  let index = 0;
  while (index < maxLength && left[index] === right[index]) {
    index += 1;
  }
  return index;
}

function normalizeImagePromptGalleryCreator(value: string) {
  return String(value || "").trim().toLowerCase().replace(/^@/, "");
}

function normalizeImagePromptGalleryUrl(value: string) {
  return String(value || "").trim().replace(/\/+$/, "");
}
