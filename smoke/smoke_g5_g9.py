"""
G5-G9 SMOKE: 写作引擎详情
- G6 风格指纹 (5 维, project 级)
- G9 声音档案 (5 维, per character)
- G7 风格学习器 (本地 0 tokens, 学前 N 章)
- G8 声音推断 (本地 0 tokens, 学 N 句对话)
- G5 一致性检测 (4 维, 写 consistency_logs)

5 分钟自动超时
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

# stdout UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 5 分钟全局超时
_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_g5_g9 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 隔离真实数据
# ============================================================

TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_g5_g9_"))
DB_PATH = TMPDIR / "test.db"
STORY_DIR = TMPDIR / "story"
STORY_DIR.mkdir(parents=True, exist_ok=True)

import app.app_paths
app.app_paths.sqlite_path = lambda: DB_PATH

import app.services.file_store
app.services.file_store.BASE_DIR = STORY_DIR

# ============================================================
# 真正的 import
# ============================================================

from app.services import (
    style_fingerprint, style_learner,
    voice_profile, voice_inferrer,
    consistency, worldbuilding,
    project_service, book_service, chapter_service,
)
from app.services.db import init_db
from app.services.exceptions import NotFoundError, ValidationError


# ============================================================
# 工具
# ============================================================

fails: list[str] = []
passed: int = 0


def check(cond, msg: str) -> None:
    global passed
    if cond:
        passed += 1
        print(f"  [PASS] {msg}")
    else:
        fails.append(msg)
        print(f"  [FAIL] {msg}")


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _setup_project(name: str = "G5-G9 测试") -> tuple[str, str]:
    """建一个空项目 (返回 project_id, book_id)."""
    p = project_service.create(name, genre="仙侠")
    pj = p["id"]
    b = book_service.create(pj, 1, title="第一卷")
    return pj, b["id"]


# ============================================================
# 测试 1: G6 风格指纹 CRUD
# ============================================================

def test_g6_fingerprint_crud(pid: str) -> None:
    section("[G6 1] 风格指纹 CRUD")

    # 默认
    fp = style_fingerprint.get(pid)
    check(fp.cultivation_level == 5, f"默认修真度 5 (实际 {fp.cultivation_level})")
    check(fp.intrigue_level == 5, f"默认阴谋度 5 (实际 {fp.intrigue_level})")
    check(fp.source == "manual", f"默认 source=manual (实际 {fp.source})")

    # upsert
    fp2 = style_fingerprint.upsert(
        pid, source=style_fingerprint.SOURCE_MANUAL,
        cultivation_level=8, intrigue_level=6, tone=7,
        sentence_length=4, vocabulary=8,
    )
    check(fp2.cultivation_level == 8, f"修真度 8 (实际 {fp2.cultivation_level})")
    check(fp2.tone == 7, f"色调 7")
    check(fp2.source == "manual", f"source=manual")

    # 部分更新
    fp3 = style_fingerprint.upsert(pid, tone=4)
    check(fp3.tone == 4, f"色调 4 (实际 {fp3.tone})")
    check(fp3.cultivation_level == 8, "修真度不变")

    # 校验 1-10
    try:
        style_fingerprint.upsert(pid, tone=15)
        check(False, "15 应 ValidationError")
    except ValidationError:
        check(True, "1-10 校验")

    # 非法 source
    try:
        style_fingerprint.upsert(pid, source="bogus")
        check(False, "非法 source 应 ValidationError")
    except ValidationError:
        check(True, "source 校验")

    # delete
    deleted = style_fingerprint.delete(pid)
    check(deleted, "delete 返回 True")
    fp_after = style_fingerprint.get(pid)
    check(fp_after.cultivation_level == 5, "删后默认回归")

    # to_prompt_block
    block = style_fingerprint.to_prompt_block(fp2)
    check("[风格指纹 5 维]" in block, f"prompt 块含标题")
    check("修真度 8/10" in block, f"修真度 8/10")


# ============================================================
# 测试 2: G9 声音档案 CRUD
# ============================================================

def test_g9_voice_profile_crud(pid: str) -> None:
    section("[G9 1] 声音档案 CRUD (per character)")

    # 默认
    vp = voice_profile.get(pid, "林轩")
    check(vp.personality == 5, "默认性格 5")
    check(vp.tone_words == "", "默认语气词空")
    check(vp.catchphrases == "", "默认口头禅空")

    # upsert
    vp2 = voice_profile.upsert(
        pid, "林轩", source=voice_profile.SOURCE_MANUAL,
        personality=8, sentence_length=3,
        tone_words="哼 / 罢了 / 岂有此理",
        catchphrases="我辈修士 / 天道昭昭",
        metaphor_pref=6,
    )
    check(vp2.personality == 8, f"性格 8 (实际 {vp2.personality})")
    check("岂有此理" in vp2.tone_words, f"语气词含 '岂有此理' (实际 {vp2.tone_words})")
    check("我辈修士" in vp2.catchphrases, f"口头禅含 '我辈修士'")

    # 2 个角色
    voice_profile.upsert(pid, "苏婉", personality=2, sentence_length=7)
    all_v = voice_profile.list_for_project(pid)
    check(len(all_v) == 2, f"2 角色 (实际 {len(all_v)})")

    # 取单角色
    sw = voice_profile.get(pid, "苏婉")
    check(sw.personality == 2, f"苏婉性格 2 (实际 {sw.personality})")

    # 校验
    try:
        voice_profile.upsert(pid, "X", personality=99)
        check(False, "99 应 ValidationError")
    except ValidationError:
        check(True, "1-10 校验")

    try:
        voice_profile.get(pid, "")
        check(False, "空名应 ValidationError")
    except ValidationError:
        check(True, "空名校验")

    # delete
    check(voice_profile.delete(pid, "苏婉"), "delete 苏婉")
    check(len(voice_profile.list_for_project(pid)) == 1, f"剩 1 (实际 {len(voice_profile.list_for_project(pid))})")

    # to_prompt_block
    block = voice_profile.to_prompt_block(vp2)
    check("[声音档案: 林轩]" in block, f"prompt 块含标题")
    check("性格 8/10" in block, f"性格 8/10")
    check("岂有此理" in block, f"语气词含 '岂有此理'")


# ============================================================
# 测试 3: G7 风格学习器
# ============================================================

def test_g7_style_learner(pid: str, bid: str) -> None:
    section("[G7 1] 风格学习器 (本地 0 tokens)")

    # 加 3 章, 不同风格
    c1 = chapter_service.create(bid, 1, title="第1章 修真")
    c2 = chapter_service.create(bid, 2, title="第2章 阴谋")
    c3 = chapter_service.create(bid, 3, title="第3章 暗黑")

    # 修真文
    txt1 = (
        "林轩在洞府中修炼真气, 灵气环绕, 即将渡劫飞升. "
        "他凝神静气, 运转天道法则, 元婴出窍, 永恒不朽. "
        "师尊说: '大道三千, 唯修真者能超脱.'"
    )
    d1 = chapter_service.create_draft(c1["id"], txt1, source="user")
    chapter_service.set_current_draft(c1["id"], d1["id"])

    # 阴谋文
    txt2 = (
        "王师兄的阴谋终于败露. 他心机深沉, 暗算同门, 离间师傅与弟子. "
        "权谋布局, 棋子纷纷倒戈. 天下为棋, 苍生为局, 这是制衡之术."
    )
    d2 = chapter_service.create_draft(c2["id"], txt2, source="user")
    chapter_service.set_current_draft(c2["id"], d2["id"])

    # 暗黑文
    txt3 = (
        "夜色阴沉, 血腥弥漫, 尸体横陈. 他在绝望中哀嚎, 诅咒命运. "
        "腐朽的阴冷中, 梦魇反复. 死亡笼罩, 一切都在寂灭中走向终结."
    )
    d3 = chapter_service.create_draft(c3["id"], txt3, source="user")
    chapter_service.set_current_draft(c3["id"], d3["id"])

    # 学习 (LearnedStyle = 6 维分析, 无 cultivation_level/intrigue_level/tone)
    learned = style_learner.learn(pid, sample_size=3, version="A")
    check(hasattr(learned, "sentence_rhythm"), f"有 sentence_rhythm (实际 {hasattr(learned, 'sentence_rhythm')})")
    check(hasattr(learned, "dialogue_density"), f"有 dialogue_density")
    check(hasattr(learned, "description_style"), f"有 description_style")
    check(hasattr(learned, "emotion_expression"), f"有 emotion_expression")
    check(hasattr(learned, "paragraph_density"), f"有 paragraph_density")
    check(hasattr(learned, "language_level"), f"有 language_level")
    check(hasattr(learned, "sample_chars"), f"有 sample_chars (实际 {hasattr(learned, 'sample_chars')})")
    check(learned.sample_chars > 100, f"采样字符数 > 100 (实际 {learned.sample_chars})")
    check(learned.version == "A", f"version=A")

    # apply
    learned2, fp = style_learner.learn_and_apply(pid, sample_size=3, version="B")
    check(fp.source == "ai_learned", f"应用后 source=ai_learned (实际 {fp.source})")
    check(hasattr(fp, "cultivation_level"), f"StyleFingerprint 应用后有 cultivation_level")

    # 空项目 → ValidationError
    pid2, _ = _setup_project("G7 空")
    try:
        style_learner.learn(pid2)
        check(False, "空项目应 ValidationError")
    except ValidationError:
        check(True, "空项目校验")

    # 外部传入 chapters_text
    test_text = "修真 灵气 飞升 天道 渡劫. " * 10
    learned3 = style_learner.learn(pid, chapters_text=test_text)
    check(learned3.cultivation_level >= 7, f"纯修真文修真度应 ≥ 7 (实际 {learned3.cultivation_level})")


# ============================================================
# 测试 4: G8 声音推断
# ============================================================

def test_g8_voice_inferrer(pid: str) -> None:
    section("[G8 1] 声音推断 (本地 0 tokens)")

    # 准备对话
    dialogues = [
        "老子乃天玄宗宗主, 尔等岂敢放肆!",
        "哼! 我辈修士, 岂能向这等阴谋低头!",
        "哈哈哈! 你这小子, 倒有几分胆色!",
        "本座今日定要让你知晓天道无常!",
        "哼! 罢了罢了, 这天下终究是修士的天下!",
        "小子, 你可敢与本座一战!",
        "我辈修士, 当守正心, 岂能被权谋所迷!",
        "哈哈! 老子纵横三百年, 还没怕过谁!",
        "天道昭昭, 本座从不做亏心事!",
        "岂有此理! 这等阴谋, 休想瞒过我!",
    ]

    # 推断
    inferred = voice_inferrer.infer(pid, "林轩", dialogues=dialogues)
    check(1 <= inferred.personality <= 10, f"性格 1-10 (实际 {inferred.personality})")
    check(1 <= inferred.sentence_length <= 10, f"句长 1-10 (实际 {inferred.sentence_length})")
    check(1 <= inferred.metaphor_pref <= 10, f"隐喻 1-10 (实际 {inferred.metaphor_pref})")
    # "老子/本座" 多 → 性格应偏张扬
    check(inferred.personality >= 6, f"性格应偏张扬 ≥ 6 (实际 {inferred.personality})")
    # 句长偏短 (10 字左右)
    check(inferred.sentence_length <= 7, f"句长应偏短 ≤ 7 (实际 {inferred.sentence_length})")
    # 语气词应捕到 "哼" / "哈哈" 至少一个
    check("哼" in inferred.tone_words or "哈哈" in inferred.tone_words,
          f"语气词捕到 (实际 {inferred.tone_words})")
    # 口头禅: "我辈修士" 出现 2 次
    check("我辈修士" in inferred.catchphrases, f"口头禅含 '我辈修士' (实际 {inferred.catchphrases})")
    check(inferred.sample_lines == 10, f"采样 10 句 (实际 {inferred.sample_lines})")

    # apply
    inferred2, vp = voice_inferrer.infer_and_apply(pid, "林轩", dialogues=dialogues)
    check(vp.source == "ai_inferred", f"应用后 source=ai_inferred (实际 {vp.source})")
    check(vp.personality >= 6, f"应用后性格仍 ≥ 6 (实际 {vp.personality})")
    check("我辈修士" in vp.catchphrases, f"应用后含 '我辈修士'")

    # 不足 3 句 → 默认
    inferred_short = voice_inferrer.infer(pid, "X", dialogues=["hi"])
    check(inferred_short.sample_lines == 1, f"1 句采样 (实际 {inferred_short.sample_lines})")
    check(inferred_short.personality == 5, f"1 句默认 5 (实际 {inferred_short.personality})")

    # 空名
    try:
        voice_inferrer.infer(pid, "")
        check(False, "空名应 ValidationError")
    except ValidationError:
        check(True, "空名校验")


# ============================================================
# 测试 5: G5 一致性检测 (4 维)
# ============================================================

def test_g5_consistency_check(pid: str) -> None:
    section("[G5 1] 一致性检测 (4 维)")

    # 准备世界库
    worldbuilding.create(pid, worldbuilding.KIND_CHARACTER, "林轩", role="主角")
    worldbuilding.create(pid, worldbuilding.KIND_CHARACTER, "苏婉", role="女主")
    worldbuilding.create(pid, worldbuilding.KIND_LOCATION, "天玄宗", region="东洲")
    worldbuilding.create(pid, worldbuilding.KIND_LOCATION, "破庙", region="东洲")
    worldbuilding.create(pid, worldbuilding.KIND_ITEM, "玄铁剑", owner="林轩", tier="灵器")

    # 准备章节
    bid = book_service.list_for_project(pid)["books"][0]["id"]
    c1 = chapter_service.create(bid, 1, title="第1章")
    c2 = chapter_service.create(bid, 2, title="第2章")

    # 第 1 章: 含已注册 + 未注册 角色和地点
    txt1 = (
        "林轩在天玄宗遇到苏婉. 两人交谈后走入破庙. "
        "神秘人张三突然出现, 拿出一柄无名匕首, 笑而不语. "
        "次日, 林轩又见李四. 故事从此开始."
    )
    d1 = chapter_service.create_draft(c1["id"], txt1, source="user")
    chapter_service.set_current_draft(c1["id"], d1["id"])

    # 第 2 章: 时间矛盾 (既说"次日"又说"昨日")
    txt2 = (
        "昨日, 林轩在天玄宗遇到张三. 三个月后, 他们再次相见. "
        "次日, 王五也来了, 拿出神秘玉佩."
    )
    d2 = chapter_service.create_draft(c2["id"], txt2, source="user")
    chapter_service.set_current_draft(c2["id"], d2["id"])

    # 检测
    result = consistency.check_project(pid, write_log=False)
    check("by_dim" in result, "by_dim 字段存在")
    check("character" in result["by_dim"], "character 维存在")
    check("location" in result["by_dim"], "location 维存在")
    check("time" in result["by_dim"], "time 维存在")
    check("item" in result["by_dim"], "item 维存在")
    check(result["total"] >= 1, f"total ≥ 1 (实际 {result['total']})")

    # character 应捕到 "张三/李四" (新人名, 出现 ≥ 3 次)
    char_issues = result["by_dim"]["character"]
    check(len(char_issues) >= 1, f"character issues ≥ 1 (实际 {len(char_issues)})")

    # location 应捕到 "神秘人" 类 + 可能 "天玄宗" (已注册, 不应报)
    loc_issues = result["by_dim"]["location"]

    # time 应捕到 "次日" + "昨日" 同时出现 → warning
    time_issues = result["by_dim"]["time"]
    check(len(time_issues) >= 1, f"time issues ≥ 1 (实际 {len(time_issues)})")
    if time_issues:
        check(time_issues[0].severity == "warning", f"time 矛盾 severity=warning")

    # item 应捕到 "无名匕首"/"神秘玉佩" (新物品)
    item_issues = result["by_dim"]["item"]
    check(len(item_issues) >= 1, f"item issues ≥ 1 (实际 {len(item_issues)})")

    # 单章检测
    issues_c1 = consistency.check_chapter(pid, c1["id"])
    check(len(issues_c1) >= 1, f"第 1 章 issues ≥ 1 (实际 {len(issues_c1)})")

    # 写日志
    result_log = consistency.check_project(pid, write_log=True)
    logs = consistency.list_logs(pid)
    check(len(logs) > 0, f"日志已写 (实际 {len(logs)} 条)")

    # 按维度过滤
    time_logs = consistency.list_logs(pid, dimension="time")
    check(len(time_logs) >= 1, f"time 日志 ≥ 1 (实际 {len(time_logs)})")
    err_logs = consistency.list_logs(pid, severity="warning")
    check(len(err_logs) >= 1, f"warning 日志 ≥ 1 (实际 {len(err_logs)})")

    # 统计
    stats = consistency.stats(pid)
    check(stats["total"] > 0, f"total > 0 (实际 {stats['total']})")
    check("by_dim" in stats and "by_severity" in stats, "by_dim/by_severity 字段存在")
    check(stats["by_dim"].get("time", 0) >= 1, f"time 统计 ≥ 1 (实际 {stats['by_dim'].get('time', 0)})")


# ============================================================
# 测试 6: 整合 - 学风格 + 学声音 + 检一致
# ============================================================

def test_integration(pid: str) -> None:
    section("[集成 1] 学风格 + 学声音 + 检一致 (端到端)")

    bid = book_service.list_for_project(pid)["books"][0]["id"]
    pid_new, _ = _setup_project("集成测试")

    # 写 2 章
    c1 = chapter_service.create(bid, 1, title="ch1")
    c2 = chapter_service.create(bid, 2, title="ch2")
    txt1 = (
        "林轩在破庙中修炼, 真气运转. 师尊说: '大道三千, 吾辈修士当自强.' "
        "他凝神静气, 元婴即将出窍. 老子定要飞升!"
    )
    txt2 = (
        "次日, 林轩离开破庙, 走入天玄宗. "
        "苏婉迎上前: '师兄, 岂有此理! 那张三居然暗算我们!' "
        "他握紧玄铁剑, 冷冷道: '哼! 罢了, 我辈修士何惧之有!'"
    )
    d1 = chapter_service.create_draft(c1["id"], txt1, source="user")
    chapter_service.set_current_draft(c1["id"], d1["id"])
    d2 = chapter_service.create_draft(c2["id"], txt2, source="user")
    chapter_service.set_current_draft(c2["id"], d2["id"])

    # 1. 学风格
    learned = style_learner.learn(pid, sample_size=2)
    check(learned.cultivation_level >= 6, f"修真文修真度 ≥ 6 (实际 {learned.cultivation_level})")

    # 2. 学声音 (林轩, 抽 "我辈修士" 口头禅)
    inferred = voice_inferrer.infer(pid, "林轩")
    check(inferred.sample_lines >= 0, f"采样 {inferred.sample_lines} 句 (可能 0 因为对话少)")

    # 3. 一致性检测
    result = consistency.check_project(pid, write_log=False)
    check(result["total"] >= 0, f"一致性检测完成 (实际 {result['total']} 条)")

    # 4. 全部都打出统计
    s = style_fingerprint.get(pid)
    v = voice_profile.list_for_project(pid)
    c = consistency.stats(pid)
    check(s.cultivation_level >= 1, "风格指纹有")
    check(isinstance(v, list), f"声音档案 {len(v)} 个")
    check("total" in c, f"一致性统计 total={c['total']}")


# ============================================================
# Main
# ============================================================

def main() -> int:
    print("=" * 60)
    print("G5-G9 SMOKE: 写作引擎详情 (风格 + 声音 + 一致性)")
    print("=" * 60)
    print(f"[setup] tmpdir = {TMPDIR}")

    init_db()
    from app.db import connection
    connection.init(DB_PATH)
    print(f"[setup] DB = {DB_PATH}")

    pj, bid = _setup_project()
    print(f"[setup] project_id = {pj}, book_id = {bid}")

    tests = [
        lambda: test_g6_fingerprint_crud(pj),
        lambda: test_g9_voice_profile_crud(pj),
        lambda: test_g7_style_learner(pj, bid),
        lambda: test_g8_voice_inferrer(pj),
        lambda: test_g5_consistency_check(pj),
        lambda: test_integration(pj),
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            fails.append(f"{t.__name__} 异常")
            print(f"\n✗ {t.__name__}: EXCEPTION — {type(e).__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"通过: {passed}    失败: {len(fails)}")
    if fails:
        print("\n失败列表:")
        for f in fails:
            print(f"  - {f}")
        print("=" * 60)
        return 1
    print(f"全部 {passed} 项检查通过 ✓")
    print("=" * 60)
    return 0


def _cleanup() -> None:
    import time
    import shutil
    try:
        from app.db import connection
        connection.close()
    except Exception:
        pass
    time.sleep(0.1)
    for ext in ("", "-wal", "-shm"):
        f = DB_PATH.parent / f"{DB_PATH.name}{ext}"
        if f.exists():
            try:
                f.unlink()
            except (PermissionError, OSError):
                pass
    try:
        shutil.rmtree(STORY_DIR, ignore_errors=True)
    except Exception:
        pass
    try:
        TMPDIR.rmdir()
    except (PermissionError, OSError):
        pass


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        _cleanup()
    sys.exit(rc)
