"""Nature 式栏目定义（展示分组，不参与 paper/essay 判定）。"""

SECTIONS = [
    {
        "slug": "this-week",
        "label": "This Week",
        "description": "本周社论、世界观与方法亮点。",
        "parts": [
            {"slug": "editorial", "label": "Editorial"},
            {"slug": "world-view", "label": "World View"},
            {"slug": "research-highlights", "label": "Research Highlights"},
        ],
    },
    {
        "slug": "news-focus",
        "label": "News in Focus",
        "description": "新闻与深度特写。",
        "parts": [
            {"slug": "news", "label": "News"},
            {"slug": "features", "label": "Features"},
        ],
    },
    {
        "slug": "books-arts",
        "label": "Books & Arts",
        "description": "书评与艺术评论。",
        "parts": [
            {"slug": "book-review", "label": "Book Review"},
            {"slug": "arts-review", "label": "Arts Review"},
        ],
    },
    {
        "slug": "opinion",
        "label": "Opinion",
        "description": "评论与读者来信。",
        "parts": [
            {"slug": "comment", "label": "Comment"},
            {"slug": "correspondence", "label": "Correspondence"},
        ],
    },
    {
        "slug": "work",
        "label": "work",
        "description": "职业、技术与科研工作现场。",
        "parts": [
            {"slug": "work-feature", "label": "Feature"},
            {"slug": "technology-feature", "label": "Technology Feature"},
        ],
    },
    {
        "slug": "research",
        "label": "Research",
        "description": "研究论文、综述与新闻评述。",
        "parts": [
            {"slug": "news-views", "label": "News & Views"},
            {"slug": "reviews", "label": "Reviews"},
            {"slug": "articles", "label": "Articles"},
        ],
    },
    {
        "slug": "amendments",
        "label": "Amendments & Corrections",
        "description": "更正、撤稿与编辑部说明。",
        "parts": [
            {"slug": "amendments-corrections", "label": "Amendments & Corrections"},
        ],
    },
    {
        "slug": "collections",
        "label": "Collections",
        "description": "专题合集与跨期聚合。",
        "parts": [{"slug": "collections", "label": "Collections"}],
    },
]

SECTION_SLUGS = {p["slug"] for s in SECTIONS for p in s["parts"]}
SECTION_LABELS = {p["slug"]: p["label"] for s in SECTIONS for p in s["parts"]}
