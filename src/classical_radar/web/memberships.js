"use strict";
// Membership and presale guide for the season page (ADR-0020). Hand-maintained, like classical-links.js: every line below was read from the
// orchestra's OWN page on `checked`, and each sale date names the page it came from. Nothing here is inferred from prices or last year, except
// the lines in `lastYear`, which the page shows as "last season's rhythm, reference only".
//   ways[].kind  "series": a subscription / season ticket (same seat for a whole series)
//                "presale": a way to buy before the general sale WITHOUT buying a series
//   sales[]      dated events of the NEXT season only: d = YYYY-MM-DD (JST), t = "HH:MM" or omitted when the page prints no time
// A date moves to "已开始" by itself (the page compares it with today); to change a fact, change it here and bump `checked`.
window.CR_MEMBERS = {
  checked: "2026-11-20",
  orchestras: {
    nhkso: {
      announced: false,
      note: "2027-28 的会员券价格和发售日官方还没公布：节目海报写明“料金、発売日等チケットの詳細は2027年4月上旬に発表予定”。",
      noteSrc: "https://www.nhkso.or.jp/news/20261009.html",
      links: [
        { label: "定期会员券", url: "https://www.nhkso.or.jp/ticket/subscription/index.html" },
        { label: "年間会员券", url: "https://www.nhkso.or.jp/ticket/subscription/annual/index.html" },
        { label: "シーズン会员券", url: "https://www.nhkso.or.jp/ticket/subscription/season/index.html" },
        { label: "购票方法", url: "https://www.nhkso.or.jp/ticket/index.html" },
      ],
      phone: "N響ガイド 0570-02-9502（平日 10:00–17:00）",
      ways: [
        { kind: "series", name: "年間会员券", text: "9月到次年6月（3月除外）同一节目、同一座位：A·C 节目各 9 回，B 节目 3 回（B 只有年间会员能买）。官网称比 1 回券便宜 15% 以上。" },
        { kind: "series", name: "シーズン会员券", text: "只有 A·C 节目，一季 3 回（AUTUMN / WINTER / SPRING 三段）。官网称比 1 回券便宜 10% 以上。" },
        { kind: "series", name: "会员特权", text: "定期公演 1 回券 10% 折扣；定期会员券、1 回券、特别公演（第九等）可在一般发售前先买；可振替到前一天或后一天（同月同节目，要预约）。" },
      ],
      lastYear: [
        "年間会员券（2026-27）：会员先行 2026-07-05，一般 07-12",
        "WINTER 季券：会员先行 2026-10-13，一般 10-16",
        "SPRING 季券：会员先行 2027-02-10，一般 02-14",
      ],
      lastYearSrc: "https://www.nhkso.or.jp/ticket/subscription/index.html",
      sales: [],
    },
    tmso: {
      announced: true,
      note: "2027年度（2027-28）的会员券已经在卖；1 回券的发售日官方页面没有写。",
      links: [
        { label: "会员券", url: "https://www.tmso.or.jp/j/member/" },
        { label: "购票方法", url: "https://www.tmso.or.jp/j/ticket/" },
        { label: "TMSOサポーター", url: "https://www.tmso.or.jp/j/support/patrons-guide/" },
        { label: "都響WEBチケット", url: "https://yyk1.ka-ruku.com/tmso-s/showList" },
      ],
      phone: "都響ガイド 0570-056-057（月–金 10:00–18:00）",
      ways: [
        { kind: "series", name: "定期A·B·C 会员、プロムナードメンバーズ", text: "A：东京艺术剧场 休日 14:00 全 8 回；B：サントリーホール 平日 19:00 全 6 回（2027 年度因场馆休馆缩为 6 回）；C：东京艺术剧场 平日 14:00 全 8 回；プロムナード：サントリーホール 休日 14:00 全 5 回。" },
        { kind: "series", name: "价格", text: "官网称 A·B·C 比 1 回券便宜约 37%，プロムナード约 30%（Ex·P 席除外）；U25 约半价。" },
        { kind: "series", name: "会员特权", text: "同座位、座位可续到下一年度、振替（A·B·C 最多 2 次，プロムナード 1 次）、1 回券先行发售、1 回券 10% 折扣。" },
        { kind: "presale", name: "TMSOサポーター", text: "1 口＝1 万日元（付款后 1 年有效）。官网特典表列有“主办公演票优先预约”，5 口起为“最优先预约”。" },
      ],
      lastYear: [],
      sales: [
        { d: "2026-10-23", what: "A·B·C 会员券、プロムナードメンバーズ 开始发售", who: "一般", src: "https://www.tmso.or.jp/j/member/",
          note: "各系列卖到首场前一个营业日（A 2027-04-09、B 2027-09-02、C 2027-05-19、プロムナード 2027-09-24），卖满会提前结束。" },
      ],
    },
    tso: {
      announced: true,
      note: "定期会员券 11/25 起东响会员先行；选べるプラン和 1 回券在 2027 年 1 月。日期取自官网各公演页上的售票信息，只适用于定期演奏会、川崎定期、东京オペラシティ三个系列。",
      links: [
        { label: "定期会员券", url: "https://tokyosymphony.jp/ticket/teiki/" },
        { label: "东响会员", url: "https://tokyosymphony.jp/membership/" },
        { label: "购票方法", url: "https://tokyosymphony.jp/ticket/" },
        { label: "在线票务", url: "https://yyk1.ka-ruku.com/tokyosymphony-s/showList" },
      ],
      phone: "TOKYO SYMPHONYチケットセンター 044-520-1511（平日 10:00–18:00）",
      ways: [
        { kind: "series", name: "定期会员券", text: "定期演奏会 10 回（サントリーホール / ミューザ川崎）、川崎定期 5 回、东京オペラシティシリーズ 6 回，三选一。同座位；官网称比 1 回券便宜约 30%；U25 半价。" },
        { kind: "series", name: "名曲全集セット券", text: "前期 5 回 / 后期 5 回 / 年间 10 回。没有东响会员折扣，也没有续座等定期会员特权。" },
        { kind: "presale", name: "在线先行", text: "免费注册 TOKYO SYMPHONY 在线票务，就能在一般发售前先买（比会员先行晚几天）。" },
        { kind: "presale", name: "东响会员", text: "会员先行 + 1 回券 10% 折扣。三种入口：サポート会员（捐助 1 万日元以上，1 年）、TOKYO SYMPHONY VISAカード（年费 1,375 日元，首年免费，办卡约需 1 个月）、定期会员。" },
      ],
      lastYear: [],
      sales: [
        // read on 2026-11-20 from the sale-date block of the official concert pages (tokyosymphony.jp/concert/<id>): of the 21 concerts of 定期演奏会 (10), 川崎定期 (5) and オペラシティシリーズ (6) that the
        // data holds for 2027-28, 20 print exactly these six dates and 1 prints four of them. 名曲全集, こども定期 and 新潟定期 print none; 第九, ニューイヤー and キッズ print other dates (not listed here).
        { d: "2026-11-25", t: "10:00", what: "定期会员券（定期演奏会·川崎定期·オペラシティ）· 东响会员先行", who: "东响会员", src: "https://tokyosymphony.jp/concert/61974",
          note: "日期取自官网各公演页（例：第756回）。三个定期系列的 21 场里有 20 场的页面印着同样的六个日期，另 1 场只印了其中 4 个；名曲全集、こども定期、新潟定期的页面没有印，第九、新年音乐会、キッズ另有日期。以各公演页为准。" },
        { d: "2026-11-30", t: "10:00", what: "定期会员券 · 在线先行", who: "注册在线票务", src: "https://tokyosymphony.jp/concert/61974" },
        { d: "2026-12-08", t: "10:00", what: "定期会员券 · 一般发售", who: "一般", src: "https://tokyosymphony.jp/concert/61974" },
        { d: "2027-01-19", t: "10:00", what: "选べるプラン·1 回券（三个定期系列）· 东响会员先行", who: "东响会员", src: "https://tokyosymphony.jp/concert/61974" },
        { d: "2027-01-22", t: "10:00", what: "选べるプラン·1 回券 · 在线先行", who: "注册在线票务", src: "https://tokyosymphony.jp/concert/61974" },
        { d: "2027-01-27", t: "10:00", what: "选べるプラン·1 回券 · 一般发售", who: "一般", src: "https://tokyosymphony.jp/concert/61974" },
      ],
    },
    jpo: {
      announced: true,
      note: "东京·横滨定期的会员券和 1 回券都已公布日期（官网日期没有印年份，按星期推定为 2026–2027 年）。",
      links: [
        { label: "2027-28 东京定期会员券", url: "https://japanphil.or.jp/ticket/subscription/2027-28tokyo/" },
        { label: "2027-28 横浜定期会员券", url: "https://japanphil.or.jp/ticket/subscription/2027-28yokohama/" },
        { label: "サポーターズクラブ", url: "https://japanphil.or.jp/support/supporter/" },
        { label: "购票方法", url: "https://japanphil.or.jp/ticket/" },
      ],
      phone: "日本フィル 03-5378-5911（平日 10:00–17:00）",
      ways: [
        { kind: "series", name: "年間定期会员券", text: "2027 年 4 月–2028 年 3 月 全 10 回（8 月、2 月除外），选金曜或土曜。官网标“年间 10 公演 36,000 日元起”“最多便宜 40%”。年间会员只接受电话。" },
        { kind: "series", name: "半期定期会员券", text: "秋冬（2027 年 10 月–2028 年 3 月，5 回）。春夏半期不再招新会员。" },
        { kind: "series", name: "会员特权", text: "专属座位、优先续座、可在 东京(金)/东京(土)/横浜 之间振替、一般发售前 1 周优先申请、1 割引。" },
        { kind: "presale", name: "サポーターズクラブ", text: "1 万日元（1 口·1 年）。主办公演一般发售前 1 周优先申请 + 10% 折扣（官网另写每口 2 张招待券，限指定公演）。" },
      ],
      lastYear: [],
      sales: [
        { d: "2026-12-16", what: "年間定期会员券（东京·横浜）开始发售", who: "一般", src: "https://japanphil.or.jp/ticket/subscription/2027-28tokyo/", note: "年间会员只接受电话 03-5378-5911。" },
        { d: "2027-01-19", what: "1 回券 · 会员先行（2027 年 4–6 月、9 月的东京定期）", who: "会员", src: "https://japanphil.or.jp/ticket/subscription/2027-28tokyo/" },
        { d: "2027-01-26", what: "1 回券 · 一般发售（同上）", who: "一般", src: "https://japanphil.or.jp/ticket/subscription/2027-28tokyo/" },
        { d: "2027-06-17", what: "秋冬半期定期会员券 开始发售", who: "一般", src: "https://japanphil.or.jp/ticket/subscription/2027-28tokyo/" },
        { d: "2027-07-06", what: "1 回券 · 会员先行（2027 年 10 月–2028 年 3 月的东京定期）", who: "会员", src: "https://japanphil.or.jp/ticket/subscription/2027-28tokyo/" },
        { d: "2027-07-13", what: "1 回券 · 一般发售（同上）", who: "一般", src: "https://japanphil.or.jp/ticket/subscription/2027-28tokyo/" },
      ],
    },
    njp: {
      announced: true,
      note: "2027/2028 的连续券（定期会员券）11/28 起分三批发售。",
      links: [
        { label: "票种与折扣", url: "https://www.njp.or.jp/ticket/service/" },
        { label: "各系列连续券", url: "https://www.njp.or.jp/concerts/subscription/" },
        { label: "パトロネージュ会员", url: "https://www.njp.or.jp/patronage/individual/" },
        { label: "购票方法", url: "https://www.njp.or.jp/ticket/" },
      ],
      phone: "新日本フィル・チケットボックス 03-5610-3815（平日 10:00–18:00，周六 10:00–15:00）",
      ways: [
        { kind: "series", name: "连续券（＝定期会员）", text: "トリフォニーホール・シリーズ 7 回（1 回券便宜 30%）；サントリーホール・シリーズ 5 回（便宜 30%；另有 2 场在东京オペラシティ，持券者可 30% 折扣买）；すみだクラシックへの扉 8 回（便宜 20%）。" },
        { kind: "series", name: "チケット・マイプラン", text: "从定期演奏会里任选 5 张以上：トリフォニー / サントリー 20% 折扣，すみだ（金·土）10%。网上、电话或窗口购买。" },
        { kind: "presale", name: "パトロネージュ会员", text: "主办演奏会优先预约 + 折扣购票。维持会员 1 口＝1 万日元，赞助会员 3 万 / 5 万 / 25 万日元。" },
        { kind: "presale", name: "NJPメンバーズカード", text: "免费入会（定价买过一次票后发卡），1 回券 10% 折扣；没有先行权。" },
      ],
      lastYear: [],
      sales: [
        { d: "2026-11-28", t: "10:00", what: "连续券 · 优先发售[1]（定期会员、パトロネージュ会员）", who: "会员", src: "https://www.njp.or.jp/ticket/service/", note: "官网标注为“2027/2028シーズン 優先発売[1]”。すみだ连续券只接受电话。" },
        { d: "2026-12-01", t: "10:00", what: "连续券 · 优先发售[2]（2026/27 チケット・マイプラン购买者）", who: "会员", src: "https://www.njp.or.jp/ticket/service/" },
        { d: "2026-12-04", t: "10:00", what: "连续券 · 一般发售", who: "一般", src: "https://www.njp.or.jp/ticket/service/" },
      ],
    },
    yomikyo: {
      announced: true,
      note: "2027-28 年度的年间会员券 12/3 起分批发售。曲目取自官方〈速報版〉PDF，之后可能调整，以读响官网最新为准。",
      links: [
        { label: "2027年度会员", url: "https://yomikyo.or.jp/info/membership.php" },
        { label: "2027-28 节目单 PDF", url: "https://yomikyo.or.jp/2026/11/2027-28web.pdf" },
        { label: "个人赞助会员", url: "https://yomikyo.or.jp/info/patronage.php" },
        { label: "购票方法", url: "https://yomikyo.or.jp/info/ticket.php" },
      ],
      ways: [
        { kind: "series", name: "年间 / 上期 / 下期会员券", text: "7 个系列：定期演奏会、名曲シリーズ（东京艺术剧场 上期 5 回 / サントリーホール 下期 5 回，19:00）、土曜·日曜マチネー（东京艺术剧场 14:00）、横浜マチネー（みなとみらいホール 14:00）、アンサンブル（TOPPANホール）、大阪定期。上期＝4–9 月，下期＝10–3 月。" },
        { kind: "series", name: "价格（定期演奏会 年间 10 回）", text: "S 席 6,580 日元/回（1 回券 9,400）、A 5,990（8,200）、B 5,250（7,000）、C 4,240（5,300）。年间比半期折扣更大。" },
        { kind: "series", name: "会员特权", text: "同座位、翌年座位优先确保、振替、1 回券先行预约 + 10% 折扣、会员限定 CD。学生会员券每系列限 30 席。" },
        { kind: "presale", name: "个人赞助会员", text: "1 口＝1 万日元（入会月起 1 年）：官网特典表列有主办公演优先预约和优待销售。" },
      ],
      lastYear: [],
      sales: [
        { d: "2026-12-03", what: "年间会员券 · 会员优先（定期演奏会、名曲シリーズ）", who: "现有会员", src: "https://yomikyo.or.jp/info/membership.php", note: "“会员优先”是给现有读响会员续订；没有会员的人从 2027-01-09 的一般发售起买。" },
        { d: "2026-12-06", what: "年间会员券 · 会员优先（土曜·日曜マチネー）", who: "现有会员", src: "https://yomikyo.or.jp/info/membership.php" },
        { d: "2026-12-09", what: "年间会员券 · 会员优先（横浜マチネー）", who: "现有会员", src: "https://yomikyo.or.jp/info/membership.php" },
        { d: "2026-12-11", what: "上期会员券 · 会员优先（定期演奏会、名曲シリーズ）", who: "现有会员", src: "https://yomikyo.or.jp/info/membership.php" },
        { d: "2027-01-09", what: "年间会员券 · 一般发售（定期、名曲、マチネー、横浜）", who: "一般", src: "https://yomikyo.or.jp/info/membership.php" },
        { d: "2027-01-11", what: "上期会员券 · 一般发售", who: "一般", src: "https://yomikyo.or.jp/info/membership.php" },
        { d: "2027-01-23", what: "大阪定期演奏会 年间会员券 · 会员优先", who: "现有会员", src: "https://yomikyo.or.jp/info/membership.php" },
        { d: "2027-02-27", what: "大阪定期演奏会 年间会员券 · 一般发售", who: "一般", src: "https://yomikyo.or.jp/info/membership.php" },
      ],
    },
    tpo: {
      announced: false,
      note: "东京爱乐的 2027-28 乐季官方还没公布（官网目前只有 2026-27）。",
      links: [
        { label: "东京フィルフレンズ（免费）", url: "https://www.tpo.or.jp/tickets/friends.php" },
        { label: "赞助会员·个人会员", url: "https://www.tpo.or.jp/support/index.php" },
        { label: "2026-27 定期演奏会", url: "https://www.tpo.or.jp/concert/2026-27season-01.php" },
      ],
      phone: "東京フィルチケットサービス 03-5353-9522（平日 10:00–18:00）",
      ways: [
        { kind: "presale", name: "东京フィルフレンズ", text: "入会费、年费都免费。主办公演票优先预约（原则上在一般发售前 1 周）+ 10% 折扣；预约要打电话。" },
      ],
      lastYear: [
        "2026-27 定期会员券：最优先（赞助会员·定期会员，电话）2025-11-21，东京フィルフレンズ优先 11-22，一般 12-09",
        "优先期间（11-22 至 12-08）在 WEB 票务买，任何人都是 9 折",
      ],
      lastYearSrc: "https://www.tpo.or.jp/information/detail-20251122-01.php",
      sales: [],
    },
  },
};
