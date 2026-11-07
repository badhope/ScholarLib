-- 20261107_unify_track_category.sql
--
-- 单一权威口径对齐：
--   content_track（paper/essay）是唯一权威轨道字段；
--   content_category 退化为子类型标签——paper 恒为 academic，
--   essay 为 fun（娱乐向）或 rant（吐槽向）。
--
-- 背景：历史上 category 是一等字段、track 由 category 派生，后来编辑部
-- 直接改 track 而 category 未同步，出现 paper+fun、essay+academic 漂移。
-- 本迁移一次性把存量 resources 对齐：paper 强制 academic，essay 非法/空
-- category 兜底 fun。数据量小（300 行级），一次性对齐；以后靠写入 helper
-- （app/core/tracks.canonicalize_track_category）保证不漂。
--
-- 幂等：可重复执行——第二次起两条 UPDATE 均命中 0 行，RAISE NOTICE 照常打印。
-- 只改 resources.content_category；不动文章正文、评分、submissions 表。
-- 由 DBA 在生产库统一执行。

DO $$
DECLARE
    before_paper_academic INT;
    before_paper_bad INT;
    before_essay_fun INT;
    before_essay_rant INT;
    before_essay_bad INT;
    before_null_track INT;
    fixed_paper INT;
    fixed_essay INT;
    after_paper_academic INT;
    after_paper_bad INT;
    after_essay_fun INT;
    after_essay_rant INT;
    after_essay_bad INT;
    after_null_track INT;
BEGIN
    -- ---------- 修复前计数 ----------
    SELECT COUNT(*) INTO before_paper_academic
      FROM resources
     WHERE content_track = 'paper' AND content_category = 'academic';
    SELECT COUNT(*) INTO before_paper_bad
      FROM resources
     WHERE content_track = 'paper'
       AND content_category IS DISTINCT FROM 'academic';  -- 含 NULL
    SELECT COUNT(*) INTO before_essay_fun
      FROM resources
     WHERE content_track = 'essay' AND content_category = 'fun';
    SELECT COUNT(*) INTO before_essay_rant
      FROM resources
     WHERE content_track = 'essay' AND content_category = 'rant';
    -- 注意：NOT IN 遇 NULL 得 NULL（不匹配），所以显式 OR content_category IS NULL。
    SELECT COUNT(*) INTO before_essay_bad
      FROM resources
     WHERE content_track = 'essay'
       AND (content_category IS NULL OR content_category NOT IN ('fun', 'rant'));
    SELECT COUNT(*) INTO before_null_track
      FROM resources
     WHERE content_track IS NULL;

    -- ---------- 修复 ----------
    -- paper 恒 academic：paper+fun / paper+NULL 等一律对齐。
    UPDATE resources
       SET content_category = 'academic'
     WHERE content_track = 'paper'
       AND content_category IS DISTINCT FROM 'academic';
    GET DIAGNOSTICS fixed_paper = ROW_COUNT;

    -- essay 只允许 fun/rant：非法值与 NULL 兜底 fun。
    -- （NOT IN 不匹配 NULL，故显式 OR content_category IS NULL。）
    UPDATE resources
       SET content_category = 'fun'
     WHERE content_track = 'essay'
       AND (content_category IS NULL OR content_category NOT IN ('fun', 'rant'));
    GET DIAGNOSTICS fixed_essay = ROW_COUNT;

    -- ---------- 修复后计数 ----------
    SELECT COUNT(*) INTO after_paper_academic
      FROM resources
     WHERE content_track = 'paper' AND content_category = 'academic';
    SELECT COUNT(*) INTO after_paper_bad
      FROM resources
     WHERE content_track = 'paper'
       AND content_category IS DISTINCT FROM 'academic';
    SELECT COUNT(*) INTO after_essay_fun
      FROM resources
     WHERE content_track = 'essay' AND content_category = 'fun';
    SELECT COUNT(*) INTO after_essay_rant
      FROM resources
     WHERE content_track = 'essay' AND content_category = 'rant';
    SELECT COUNT(*) INTO after_essay_bad
      FROM resources
     WHERE content_track = 'essay'
       AND (content_category IS NULL OR content_category NOT IN ('fun', 'rant'));
    SELECT COUNT(*) INTO after_null_track
      FROM resources
     WHERE content_track IS NULL;

    RAISE NOTICE '=== unify_track_category: 修复前 ===';
    RAISE NOTICE '  paper : academic=% bad(含fun/rant/NULL)=%', before_paper_academic, before_paper_bad;
    RAISE NOTICE '  essay : fun=% rant=% bad(含academic/NULL)=%', before_essay_fun, before_essay_rant, before_essay_bad;
    RAISE NOTICE '  track=NULL : %', before_null_track;
    RAISE NOTICE '=== unify_track_category: 修复行数 ===';
    RAISE NOTICE '  paper→academic 修复 % 行', fixed_paper;
    RAISE NOTICE '  essay→fun 修复 % 行（含 academic/NULL）', fixed_essay;
    RAISE NOTICE '=== unify_track_category: 修复后 ===';
    RAISE NOTICE '  paper : academic=% bad=%', after_paper_academic, after_paper_bad;
    RAISE NOTICE '  essay : fun=% rant=% bad=%', after_essay_fun, after_essay_rant, after_essay_bad;
    RAISE NOTICE '  track=NULL : %（读接口按 category 回推，不归此迁移管）', after_null_track;
END $$;
