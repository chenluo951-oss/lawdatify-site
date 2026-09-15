/* 引源分级 · 浏览器端实现（与 sources_tier.py 同口径，改一处要同步改另一处）
 *
 * 站点硬规则：立法 / 标准发布生效 / 合规专项行动 / 监管处罚案例，
 * 必须引用官方账号原文（official / wechat-official）；合规资讯可引官方媒体
 * （gov-media）与官方学术机构、协会组织（academic）以及专业研究解读（research）。
 * 二手转载（other）不可作为依据。
 *
 * wechat-official：发布机关自己的微信公众号。地方监管局的典型案例常只在公众号
 * 发布、PC 官网无对应页，因此单列一档。但公众号域名不含机构信息，必须有凭据
 * （__biz 命中白名单，或数据里显式声明 src="wechat-official"）才放行，否则仍算 other。
 *
 * research：高校研究机构、专业学术号与行业律所团队发布的合规研究与实务解读
 * （如「数据法学」「网数与人工智能法律实务」）。属研究观点，可用于资讯与解读，
 * 不作为监管依据。同样要求凭据（账号名命中白名单，或声明 src="research"）。
 */
(function () {
  var LABEL = {
    official: '官方原文',
    'wechat-official': '官方公众号',
    'gov-media': '官方媒体',
    academic: '专业机构',
    research: '研究观点',
    other: '二手转载'
  };
  var CLASS = {
    official: 'src-off',
    'wechat-official': 'src-wx',
    'gov-media': 'src-media',
    academic: 'src-aca',
    research: 'src-res',
    other: 'src-oth'
  };

  var WECHAT_HOSTS = ['mp.weixin.qq.com', 'weixin.qq.com'];
  var WECHAT_BIZ = [
    'MzA5MjM0NTQ2Mw==',  // 市说新语（市场监管总局）
    'Mzg3MDA1NTQxNw=='   // 网信中国（中央网信办）
  ];

  /* 官方协会 / 学会 / 研究院类账号名特征词 → academic */
  var ASSOCIATION_KEYS = ['协会', '学会', '委员会', '研究院', '研究所', '信通院',
    '标准化技术', '产业联盟', '联合会', '促进会', '商会', '仲裁委', '认证中心'];
  /* 研究 / 学术号与行业律所团队 → research */
  var RESEARCH_ACCOUNTS = ['数据法学', '数字法治', '网络法前哨', '数据合规公社',
    '个人信息保护合规审计', '数据安全推进计划', '数字经济发展与治理', '数字经济与社会',
    '网络空间治理', '人工智能治理', '清华大学人工智能国际治理研究院',
    '中国政法大学数据法治研究院', '中国人民大学未来法治研究院',
    '北京大学法治与发展研究院', '网数与人工智能法律实务', 'tmt法律论坛',
    '汉坤', '中伦', '金杜', '数据合规评论', '网络与数据法律实务'];
  /* 发布机关号 → wechat-official */
  var WECHAT_ACCOUNTS = ['市说新语', '网信中国', '网安局', '公安部网安局', '市场监管',
    '市场监督管理局', '市场监管局', '监督管理局', '网信办', '人民政府', '融媒', '发布',
    '市场监管半月沙龙', '互联网信息办公室', '网络安全和信息化'];
  /* 省级 / 重点城市网信办官方号：「网信+行政区名」 */
  var REGION_RX = /网信(中国|北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|内蒙古|广西|西藏|宁夏|新疆|深圳|青岛|宁波|厦门|大连)/;

  var OFFICIAL_HOSTS = [
    'npc.gov.cn', 'flk.npc.gov.cn', 'cac.gov.cn', 'beian.cac.gov.cn', '12377.cn',
    'miit.gov.cn', 'samr.gov.cn', 'openstd.samr.gov.cn', 'mohrss.gov.cn',
    'nhc.gov.cn', 'zwfw.nhc.gov.cn', 'mofcom.gov.cn', 'trb.mofcom.gov.cn',
    'court.gov.cn', 'spp.gov.cn', 'mps.gov.cn', 'moj.gov.cn', 'ndrc.gov.cn',
    'mof.gov.cn', 'mot.gov.cn', 'moa.gov.cn', 'most.gov.cn', 'customs.gov.cn',
    'nea.gov.cn', 'nmpa.gov.cn', 'stats.gov.cn', 'sasac.gov.cn', 'gov.cn',
    'ec.europa.eu', 'digital-strategy.ec.europa.eu', 'eur-lex.europa.eu',
    'edpb.europa.eu', 'europa.eu', 'ftc.gov', 'oag.ca.gov', 'ico.org.uk',
    'pdpc.gov.sg', 'meity.gov.in', 'gov.br', 'oecd.org', 'un.org', 'unesco.org'
  ];
  var MEDIA_HOSTS = [
    'people.com.cn', 'cpc.people.com.cn', 'xinhuanet.com', 'news.cn', 'cctv.com',
    'cnr.cn', 'gmw.cn', 'chinanews.com.cn', 'ce.cn', 'china.com.cn',
    'qstheory.cn', 'stdaily.com', 'thepaper.cn', 'jfdaily.com'
  ];
  var ACADEMIC_HOSTS = [
    'caict.ac.cn', 'tc260.org.cn', 'cnis.ac.cn', 'sacinfo.org.cn', 'isc.org.cn',
    'cybersac.cn', 'cca.org.cn', 'chinawuliu.com.cn', 'ccas.com.cn',
    'chinacpi.org', 'cagp.org.cn', 'ssrn.com', 'arxiv.org', 'papers.ssrn.com'
  ];

  function hostOf(url) {
    try {
      return new URL(url, location.href).hostname.toLowerCase().replace(/^www\./, '');
    } catch (e) {
      return '';
    }
  }

  function containsAny(list, s) {
    for (var i = 0; i < list.length; i++) {
      if (s.indexOf(list[i].toLowerCase()) >= 0) return true;
    }
    return false;
  }

  function accountTier(name) {
    var a = (name || '').trim().toLowerCase();
    if (!a) return 'other';
    if (containsAny(RESEARCH_ACCOUNTS, a)) return 'research';
    if (containsAny(ASSOCIATION_KEYS, a)) return 'academic';
    if (REGION_RX.test(a)) return 'wechat-official';
    if (containsAny(WECHAT_ACCOUNTS, a)) return 'wechat-official';
    return 'other';
  }

  function wechatTier(url, declared, account) {
    if (declared === 'wechat-official' || declared === 'official') return 'wechat-official';
    if (declared === 'research' || declared === 'expert') return 'research';
    var m = /[?&]__biz=([^&#]+)/.exec(url || '');
    if (m) {
      var biz = decodeURIComponent(m[1]);
      if (WECHAT_BIZ.indexOf(biz) >= 0) return 'wechat-official';
    }
    return accountTier(account);
  }

  /* account：公众号账号名（公众号域名不含机构信息，需靠账号名白名单放行） */
  function tierOf(url, declared, account) {
    var h = hostOf(url);
    if (!h) {
      if (declared === 'official') return 'official';
      if (declared === 'analysis' || declared === 'academic') return 'academic';
      if (declared === 'wechat-official') return 'wechat-official';
      if (declared === 'research' || declared === 'expert') return 'research';
      return accountTier(account);
    }
    if (WECHAT_HOSTS.indexOf(h) >= 0) return wechatTier(url, declared, account);
    if (OFFICIAL_HOSTS.indexOf(h) >= 0 || MEDIA_HOSTS.indexOf(h) >= 0 ||
        ACADEMIC_HOSTS.indexOf(h) >= 0) {
      if (OFFICIAL_HOSTS.indexOf(h) >= 0) return 'official';
      if (MEDIA_HOSTS.indexOf(h) >= 0) return 'gov-media';
      return 'academic';
    }
    if (/gov\.cn$/.test(h) || /(^|\.)gov(\.[a-z]{2})?$/.test(h) || /europa\.eu$/.test(h) ||
        /\.(go\.jp|go\.kr|gouv\.[a-z]{2}|gob\.[a-z]{2}|gov\.uk|gov\.au|gov\.hk|gov\.mo)$/.test(h)) {
      return 'official';
    }
    if (/(people\.com\.cn|xinhuanet\.com|news\.cn|cctv\.com|gmw\.cn|ce\.cn|thepaper\.cn|cnr\.cn|chinanews\.com\.cn|qstheory\.cn|stdaily\.com)$/.test(h)) {
      return 'gov-media';
    }
    if (/\.(edu\.cn|ac\.cn|edu|ac\.uk|org\.cn)$/.test(h)) return 'academic';
    return 'other';
  }

  function srcTierTag(url, declared, account) {
    var t = tierOf(url, declared, account);
    return '<span class="rd-src ' + CLASS[t] + '">' + LABEL[t] + '</span>';
  }

  window.SRC_TIER = { LABEL: LABEL, CLASS: CLASS, tierOf: tierOf, tag: srcTierTag,
    accountTier: accountTier };
  window.srcTierOf = tierOf;
  window.srcTierTag = srcTierTag;
})();
