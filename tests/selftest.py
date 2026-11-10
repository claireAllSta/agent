#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOT-1 年会抽奖程序（重做版 v2）自测脚本
覆盖图样 bc8b55da 的 12 条验收标准，使用 Playwright + Chromium 真浏览器。

用法：
    python3 tests/selftest.py

输出：
    - 终端逐条 PASS / FAIL 与汇总
    - tests/artifacts/selftest-report.json
    - tests/artifacts/screenshot-1920x1080.png
    - tests/artifacts/screenshot-1366x768.png
退出码：0 全部通过；1 有失败。
"""
import json
import os
import re
import sys
import time
import hashlib
import pathlib

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "index.html"
ART = pathlib.Path(__file__).resolve().parent / "artifacts"
ART.mkdir(parents=True, exist_ok=True)
REPORT = ART / "selftest-report.json"

RESULTS = []
START = time.time()


def record(tid, criterion, desc, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    RESULTS.append({
        "id": tid,
        "criterion": criterion,
        "desc": desc,
        "status": status,
        "detail": detail,
    })
    print(f"{status} {tid:<22} {desc} | {detail}", flush=True)
    return ok


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


DEFAULT_NAMES = "陈思远,林晓,郑凯,谢雨,韩磊,唐敏,冯雪,董浩,萧然,程静,曹阳,袁野,邓宇,许宁,傅明,沈悦,曾诚,彭飞,吕航,苏婉"


def reset(page):
    page.evaluate("window.__lottery.reset()")
    page.wait_for_timeout(60)


def reset_default(page):
    """恢复 20 人默认名单与干净状态（避免前一用例导入的小名单影响后续）。"""
    page.evaluate(f"window.__lottery.importNames({json.dumps(DEFAULT_NAMES, ensure_ascii=False)})")
    page.wait_for_timeout(60)


def state(page):
    return page.evaluate("window.__lottery.getState()")


def count(page, sel):
    return page.eval_on_selector_all(sel, "els => els.length")


def draw_once(page, roll_ms=90):
    page.evaluate("window.__lottery.startRoll()")
    page.wait_for_timeout(roll_ms)
    page.evaluate("window.__lottery.stopRoll()")
    page.wait_for_timeout(40)


def text(page, sel):
    return page.inner_text(sel).strip()


def rect(page, sel):
    return page.eval_on_selector(sel, """el => {
        const r = el.getBoundingClientRect();
        return {x:r.x, y:r.y, width:r.width, height:r.height, right:r.right, bottom:r.bottom};
    }""")


def alpha_pixels(page):
    return page.evaluate("""() => {
        const c = document.getElementById('confetti');
        const ctx = c.getContext('2d');
        const d = ctx.getImageData(0, 0, c.width, c.height).data;
        let n = 0;
        for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
        return n;
    }""")


def main():
    html = PAGE.read_text(encoding="utf-8")
    url = PAGE.resolve().as_uri()

    # ---------- 1. 单文件 / 零外部资源 ----------
    try:
        low = html.lower()
        forbidden = {
            "http(s) 协议": ("http://" in low) or ("https://" in low),
            "<script src>": "<script src" in low,
            "<link>": "<link" in low,
            "url(...)": "url(" in low,
            "@import": "@import" in low,
            "fetch(": "fetch(" in low,
            "XMLHttpRequest": "xmlhttprequest" in low,
            "WebSocket": "websocket" in low,
            "EventSource": "eventsource" in low,
            "eval(": "eval(" in low,
            "new Function": "new function" in low,
        }
        bad = [k for k, v in forbidden.items() if v]
        record("1-static", 1, "单文件且无任何外部资源引用",
               len(bad) == 0, f"命中黑名单 {bad}" if bad else "11 项静态扫描全部为 0")
        record("1-file", 1, "交付目录仅一个 HTML 文件",
               len(list(ART.parent.parent.glob("*.html"))) == 1,
               f"html 文件数={len(list(ART.parent.parent.glob('*.html')))}")
    except Exception as exc:  # noqa: BLE001
        record("1-static", 1, "单文件且无任何外部资源引用", False, f"异常 {exc}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        # ---------- 1. 断网/零外部请求 + 2/4/5/6/7/8/9/11 ----------
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()
        net = []
        console_errors = []
        page_errors = []

        def route_handler(route):
            req_url = route.request.url
            if req_url.startswith("file:"):
                net.append(req_url)
                route.continue_()
            else:
                net.append("BLOCKED " + req_url)
                route.abort()

        page.route("**/*", route_handler)
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        page.goto(url)
        page.wait_for_function("window.__lottery && window.__lottery.version === '2.0.0'")
        page.wait_for_timeout(200)

        try:
            external = [u for u in net if not u.startswith("file:")]
            record("1-network", 1, "运行时无任何外部网络请求",
                   len(external) == 0, f"请求 {len(net)} 条，非 file 请求 {len(external)} 条")
        except Exception as exc:  # noqa: BLE001
            record("1-network", 1, "运行时无任何外部网络请求", False, f"异常 {exc}")

        # 2. 默认 20 人
        try:
            st = state(page)
            names = st["roster"]
            record("2-default", 2, "首次打开显示 20 个示例姓名，总人数 20",
                   len(names) == 20 and len(set(names)) == 20 and len(st["pool"]) == 20
                   and text(page, "#totalCount") == "20"
                   and text(page, "#remainCount") == "20"
                   and count(page, ".chip") == 20,
                   f"total={text(page, '#totalCount')} remain={text(page, '#remainCount')} chips={count(page, '.chip')}")
        except Exception as exc:  # noqa: BLE001
            record("2-default", 2, "首次打开显示 20 个示例姓名，总人数 20", False, f"异常 {exc}")

        # 3. 导入去空行 / 去重
        try:
            page.click("#importBtn")
            page.fill("#rosterInput", "  张三  \n李四、王五\n\n张三\n李四,赵六， 孙七 周八;吴九；郑十")
            page.click("#confirmImport")
            page.wait_for_timeout(120)
            st = state(page)
            expect = ["张三", "李四", "王五", "赵六", "孙七", "周八", "吴九", "郑十"]
            record("3-import", 3, "导入含空行与重复姓名后自动去空行、去重",
                   st["roster"] == expect and text(page, "#totalCount") == "8"
                   and text(page, "#remainCount") == "8",
                   f"roster={st['roster']} total={text(page, '#totalCount')}")
        except Exception as exc:  # noqa: BLE001
            record("3-import", 3, "导入含空行与重复姓名后自动去空行、去重", False, f"异常 {exc}")

        # 4. 开始滚动 / 停止定格 1 人；空格、回车
        try:
            reset(page)
            page.click("#drawBtn")
            page.wait_for_timeout(30)
            names = set()
            for _ in range(7):
                names.add(text(page, "#displayName"))
                page.wait_for_timeout(60)
            rolling_btn = text(page, "#drawBtn")
            page.click("#drawBtn")
            page.wait_for_timeout(80)
            st = state(page)
            record("4-mouse", 4, "点击开始进入滚动、点击停止定格 1 人",
                   len(names) >= 3 and "停止" in rolling_btn and st["rolling"] is False
                   and len(st["winners"]) == 1 and text(page, "#displayName") == st["winners"][0]["name"],
                   f"滚动采样 {len(names)} 个不同姓名，停止后 winners={len(st['winners'])}")
        except Exception as exc:  # noqa: BLE001
            record("4-mouse", 4, "点击开始进入滚动、点击停止定格 1 人", False, f"异常 {exc}")

        try:
            reset(page)
            page.locator("body").click(position={"x": 8, "y": 8})
            page.keyboard.press("Space")
            page.wait_for_timeout(120)
            sp1 = state(page)["rolling"]
            page.keyboard.press("Space")
            page.wait_for_timeout(120)
            sp2 = state(page)["rolling"]
            page.keyboard.press("Enter")
            page.wait_for_timeout(120)
            en1 = state(page)["rolling"]
            page.keyboard.press("Enter")
            page.wait_for_timeout(120)
            st = state(page)
            record("4-keys", 4, "空格、回车均可完成开始 / 停止",
                   sp1 is True and sp2 is False and en1 is True and st["rolling"] is False
                   and len(st["winners"]) == 2,
                   f"space {sp1}->{sp2}，enter {en1}->{st['rolling']}，winners={len(st['winners'])}")
        except Exception as exc:  # noqa: BLE001
            record("4-keys", 4, "空格、回车均可完成开始 / 停止", False, f"异常 {exc}")

        # 5. 撒花 + 中奖者移出奖池、不重复
        try:
            reset_default(page)
            before = state(page)
            page.evaluate("window.__lottery.startRoll()")
            page.wait_for_timeout(120)
            page.evaluate("window.__lottery.stopRoll()")
            page.wait_for_timeout(260)
            px = alpha_pixels(page)
            st = state(page)
            winner = st["winners"][0]["name"]
            record("5-confetti", 5, "停止揭晓时撒花（Canvas 像素证据）",
                   px > 0, f"alpha 像素={px}")
            record("5-remove", 5, "中奖者移出奖池",
                   winner not in st["pool"] and len(st["pool"]) == len(before["pool"]) - 1,
                   f"winner={winner} remain={len(st['pool'])}")
            # 连抽 20 轮，验证不重复
            reset_default(page)
            for _ in range(20):
                draw_once(page)
            st = state(page)
            wnames = [w["name"] for w in st["winners"]]
            record("5-norepeat", 5, "后续抽奖不再出现已中奖者",
                   len(wnames) == 20 and len(set(wnames)) == 20 and st["pool"] == [],
                   f"20 轮中奖 {len(wnames)} 人，唯一 {len(set(wnames))} 人，剩余 {len(st['pool'])}")
        except Exception as exc:  # noqa: BLE001
            record("5-confetti", 5, "停止揭晓时撒花（Canvas 像素证据）", False, f"异常 {exc}")

        # 6. 轮次记录
        try:
            items = page.eval_on_selector_all(".winner-item", """els => els.map(e => ({
                round: e.querySelector('.round-tag').textContent.trim(),
                name: e.querySelector('.win-name').textContent.trim(),
                text: e.textContent.replace(/\\s+/g, ' ').trim()
            }))""")
            st = state(page)
            ok = len(items) == 20
            ok = ok and [w["round"] for w in st["winners"]] == list(range(1, 21))
            ok = ok and all(re.match(r"^第 %d 轮$" % (i + 1), items[i]["round"]) for i in range(20))
            ok = ok and all(items[i]["name"] == st["winners"][i]["name"] for i in range(20))
            record("6-rounds", 6, "中奖名单按「第 N 轮 — 姓名」逐条追加，轮次连续",
                   ok, f"记录 {len(items)} 条，轮次 1..{len(items)}")
        except Exception as exc:  # noqa: BLE001
            record("6-rounds", 6, "中奖名单按「第 N 轮 — 姓名」逐条追加，轮次连续", False, f"异常 {exc}")

        # 7. 重抽本轮
        try:
            reset(page)
            page.evaluate("window.__lottery.importNames('甲一,乙二,丙三,丁四')")
            page.wait_for_timeout(60)
            draw_once(page)
            w1 = state(page)["winners"][0]
            page.evaluate("window.__lottery.redrawRound()")
            page.wait_for_timeout(60)
            st = state(page)
            returned = w1["name"] in st["pool"]
            cleared = (st["winners"] == [] and count(page, ".winner-item") == 0
                       and text(page, "#roundBadge") == "第 1 轮")
            draw_once(page)
            st2 = state(page)
            record("7-redraw", 7, "重抽本轮：姓名回池、记录替换、可再次抽中",
                   returned and cleared and len(st2["winners"]) == 1
                   and st2["winners"][0]["round"] == 1,
                   f"回池={returned} 清记录={cleared} 再抽轮次={st2['winners'][0]['round'] if st2['winners'] else '无'}")
        except Exception as exc:  # noqa: BLE001
            record("7-redraw", 7, "重抽本轮：姓名回池、记录替换、可再次抽中", False, f"异常 {exc}")

        # 8. 全部重置二次确认
        try:
            reset_default(page)
            draw_once(page)
            draw_once(page)
            before = state(page)
            page.click("#resetBtn")
            page.wait_for_timeout(60)
            visible = page.is_visible("#resetModal")
            page.click("#cancelReset")
            page.wait_for_timeout(60)
            after_cancel = state(page)
            page.click("#resetBtn")
            page.wait_for_timeout(60)
            page.click("#confirmReset")
            page.wait_for_timeout(80)
            after_confirm = state(page)
            record("8-reset", 8, "全部重置先二次确认；取消不变、确认清空并恢复奖池",
                   visible and after_cancel["winners"] == before["winners"]
                   and after_confirm["winners"] == [] and len(after_confirm["pool"]) == 20
                   and count(page, ".winner-item") == 0,
                   f"弹窗={visible} 取消后 {len(after_cancel['winners'])} 条，确认后 {len(after_confirm['winners'])} 条 / 奖池 {len(after_confirm['pool'])}")
        except Exception as exc:  # noqa: BLE001
            record("8-reset", 8, "全部重置先二次确认；取消不变、确认清空并恢复奖池", False, f"异常 {exc}")

        # 9. 标题可改 + 刷新保留 + 标题内空格不误触
        try:
            ctx.clear_cookies()
            page.evaluate("localStorage.removeItem('hifox.lottery.titles.v2')")
            page.reload()
            page.wait_for_function("window.__lottery && window.__lottery.version === '2.0.0'")
            page.wait_for_timeout(120)
            defaults = (text(page, "#companyName"), text(page, "#galaTitle"))

            page.click("#companyName")
            page.evaluate("""() => { const el=document.getElementById('companyName');
                const r=document.createRange(); r.selectNodeContents(el);
                const s=getSelection(); s.removeAllRanges(); s.addRange(r); el.focus(); }""")
            page.keyboard.type("狐厂测试科技有限公司")
            page.keyboard.press("Enter")
            page.click("#galaTitle")
            page.evaluate("""() => { const el=document.getElementById('galaTitle');
                const r=document.createRange(); r.selectNodeContents(el);
                const s=getSelection(); s.removeAllRanges(); s.addRange(r); el.focus(); }""")
            page.keyboard.type("新春年会")
            page.keyboard.press("Enter")
            page.wait_for_timeout(120)
            page.reload()
            page.wait_for_function("window.__lottery && window.__lottery.version === '2.0.0'")
            page.wait_for_timeout(120)
            persisted = (text(page, "#companyName"), text(page, "#galaTitle"))

            # 标题内按空格不触发抽奖
            page.click("#galaTitle")
            page.keyboard.press("Space")
            page.keyboard.press("Space")
            page.wait_for_timeout(100)
            st = state(page)
            no_draw = (st["rolling"] is False and len(st["winners"]) == 0)

            record("9-title", 9, "公司名 / 年会标题可改且刷新保留",
                   defaults == ("小狐科技有限公司", "年会盛典")
                   and persisted == ("狐厂测试科技有限公司", "新春年会"),
                   f"默认={defaults} 刷新后={persisted}")
            record("9-space", 9, "标题内输入空格不误触抽奖",
                   no_draw, f"空格后 rolling={st['rolling']} winners={len(st['winners'])}")
        except Exception as exc:  # noqa: BLE001
            record("9-title", 9, "公司名 / 年会标题可改且刷新保留", False, f"异常 {exc}")

        # 11. 空奖池提示 / 不空抽 / 重置后可继续
        try:
            page.evaluate("window.__lottery.importNames('甲,乙')")
            page.wait_for_timeout(50)
            draw_once(page)
            draw_once(page)
            st = state(page)
            page.click("#drawBtn")
            page.wait_for_timeout(160)
            st2 = state(page)
            toast = text(page, "#toast")
            record("11-empty", 11, "奖池抽完提示且不空抽",
                   len(st["pool"]) == 0 and st2["rolling"] is False
                   and len(st2["winners"]) == 2 and "奖池已抽完" in toast,
                   f"池空后点击：rolling={st2['rolling']} winners={len(st2['winners'])} toast={toast!r}")
            page.click("#resetBtn")
            page.wait_for_timeout(50)
            page.click("#confirmReset")
            page.wait_for_timeout(60)
            draw_once(page)
            st3 = state(page)
            record("11-after-reset", 11, "重置后可继续抽奖",
                   len(st3["winners"]) == 1 and len(st3["pool"]) == 1,
                   f"重置后再抽 winners={len(st3['winners'])} pool={len(st3['pool'])}")
        except Exception as exc:  # noqa: BLE001
            record("11-empty", 11, "奖池抽完提示且不空抽", False, f"异常 {exc}")

        # 0. JS 报错
        try:
            record("0-js-errors", 0, "全程无 JavaScript 报错",
                   len(console_errors) == 0 and len(page_errors) == 0,
                   f"console.error={len(console_errors)} pageerror={len(page_errors)}")
        except Exception as exc:  # noqa: BLE001
            record("0-js-errors", 0, "全程无 JavaScript 报错", False, f"异常 {exc}")

        ctx.close()

        # ---------- 10. 两视口布局 ----------
        for width, height in ((1920, 1080), (1366, 768)):
            tag = f"10-layout-{width}x{height}"
            try:
                vctx = browser.new_context(viewport={"width": width, "height": height})
                vpage = vctx.new_page()
                vpage.goto(url)
                vpage.wait_for_function("window.__lottery && window.__lottery.version === '2.0.0'")
                vpage.wait_for_timeout(180)

                metrics = vpage.evaluate("""() => ({
                    sw: document.documentElement.scrollWidth,
                    cw: document.documentElement.clientWidth,
                    innerW: innerWidth
                })""")
                boxes = {
                    "topbar": rect(vpage, ".topbar"),
                    "stage": rect(vpage, "#stage"),
                    "roster": rect(vpage, ".roster-panel"),
                    "winners": rect(vpage, ".winners-panel"),
                    "display": rect(vpage, "#displayName"),
                    "drawBtn": rect(vpage, "#drawBtn"),
                    "winnerList": rect(vpage, "#boardScroll"),
                }
                inside = {}
                for name, r in boxes.items():
                    inside[name] = (r["x"] >= -1 and r["y"] >= -1
                                    and r["right"] <= width + 1 and r["bottom"] <= height + 1
                                    and r["width"] > 0 and r["height"] > 0)
                no_overlap = (boxes["stage"]["x"] >= boxes["roster"]["right"] - 1
                              and boxes["winners"]["x"] >= boxes["stage"]["right"] - 1)
                display_clip = vpage.eval_on_selector(
                    "#displayName", "el => el.scrollWidth <= el.clientWidth + 2")
                ok = (metrics["sw"] <= metrics["cw"] + 1 and all(inside.values())
                      and no_overlap and display_clip)
                vpage.screenshot(path=str(ART / f"screenshot-{width}x{height}.png"))
                record(tag, 10, f"{width}×{height} 无横向滚动、无重叠、主区与名单完整可见",
                       ok,
                       f"scrollW={metrics['sw']}/{metrics['cw']} 视口内={sum(inside.values())}/{len(inside)} "
                       f"无重叠={no_overlap} 姓名不截断={display_clip}")

                # 20 人中奖压力
                vpage.evaluate("window.__lottery.reset()")
                for _ in range(20):
                    draw_once(vpage, 45)
                stress = vpage.evaluate("""() => {
                    const scroll = document.getElementById('boardScroll');
                    const last = document.querySelector('.winner-item:last-child');
                    const panel = document.querySelector('.winners-panel').getBoundingClientRect();
                    const lr = last.getBoundingClientRect();
                    return {
                        count: document.querySelectorAll('.winner-item').length,
                        scrollable: scroll.scrollHeight >= scroll.clientHeight,
                        lastWithinPanel: lr.bottom <= panel.bottom + 2 && lr.top >= panel.top - 2,
                        panelRight: panel.right, innerW: innerWidth
                    };
                }""")
                record(tag + "-stress", 10, f"{width}×{height} 20 人中奖后名单可滚动且面板完整",
                       stress["count"] == 20 and stress["scrollable"]
                       and stress["lastWithinPanel"] and stress["panelRight"] <= stress["innerW"] + 1,
                       json.dumps(stress, ensure_ascii=False))
                vctx.close()
            except Exception as exc:  # noqa: BLE001
                record(tag, 10, f"{width}×{height} 布局检查", False, f"异常 {exc}")

        browser.close()

    # ---------- 12. 交付文件同一性（附件由外部上传后核验） ----------
    digest = sha256(PAGE)
    record("12-file", 12, "交付 HTML 单文件可打开（SHA-256 记录，附件一致性另行核验）",
           PAGE.exists() and PAGE.stat().st_size > 10000,
           f"{PAGE.name} {PAGE.stat().st_size} B sha256={digest}")

    total = len(RESULTS)
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = total - passed
    elapsed = time.time() - START
    payload = {
        "version": "2.0.0",
        "page": str(PAGE),
        "sha256": digest,
        "size": PAGE.stat().st_size,
        "elapsedSeconds": round(elapsed, 2),
        "summary": {"total": total, "passed": passed, "failed": failed},
        "results": RESULTS,
    }
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("-" * 72, flush=True)
    print(f"SUMMARY {passed}/{total} passed in {elapsed:.1f}s", flush=True)
    print(f"REPORT {REPORT}", flush=True)
    if failed:
        print("FAILED:", ", ".join(r["id"] for r in RESULTS if r["status"] == "FAIL"), flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
